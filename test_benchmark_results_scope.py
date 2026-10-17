"""Directive 11C (T3): BENCHMARK_RESULTS.json must describe its own scope.

The file reported

    "total": 500, "passed": 500, "pass_rate": 1.0
    "by_metric": { ..., "execution": {"total": 500, "passed": 500}, ... }

with nothing in it saying what those numbers were measured against. A
reader would reasonably read a passing `execution` metric as proof that
Genesis performed 500 real OS operations.

It did not. `benchmark/runner.py` drives a `_MockOSManager` and mocked
agents so the run is reproducible and needs no network, API key or real
desktop. Every metric in that file is a check against a mock.

Two separate defects, both fixed here:

  1. NO SCOPE. The file claimed a bare 100%. It now carries an explicit
     `scope` block saying what it is, what it is NOT, that no OS
     operation was executed, and that it is not acceptance evidence.

  2. NOT VERSIONED. The file was written two levels UP, at
     <repo-parent>/BENCHMARK_RESULTS.json -- OUTSIDE the git repo -- and
     had never been committed. So the honesty fix could not be reviewed
     or diffed, and the next `python -m benchmark` would rewrite the
     artifact silently.

The important durability property: the label is emitted by
`render_json_report`, not hand-written into the JSON. Labelling the
checked-in file by hand would be undone by the next regeneration, which
is precisely the failure being fixed.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent
RESULTS = BACKEND / "benchmark" / "BENCHMARK_RESULTS.json"

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


@pytest.fixture(scope="module")
def results():
    assert RESULTS.is_file(), f"{RESULTS} is missing"
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def _scope_text(results):
    return results["scope"]["what_this_is"]


# =====================================================================
# The file is versioned and in the repository
# =====================================================================

def test_the_results_file_lives_inside_the_repository():
    """It used to be written two levels up, outside the git root."""
    assert RESULTS.is_file(), RESULTS
    assert BACKEND in RESULTS.parents
    assert (BACKEND / "benchmark" / "__init__.py").is_file()


def test_nothing_writes_the_report_outside_the_repository():
    """The write path was the reason the file was unversioned."""
    source = (BACKEND / "benchmark" / "report.py").read_text(
        encoding="utf-8-sig"
    )
    assert '"..", "..", "BENCHMARK_RESULTS.json"' not in source, (
        "report.py still writes the report outside the repository"
    )
    assert "C:/Users/" not in source, (
        "report.py contains a hardcoded absolute machine path"
    )


def test_no_tracked_file_hardcodes_the_old_outside_path():
    """dump_failures.py had this machine's absolute path baked in.

    Test files are excluded: this one necessarily contains the very
    string it searches for, and a scanner that flags itself proves
    nothing.
    """
    offenders = []
    for path in BACKEND.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if "gemini_cli/BENCHMARK_RESULTS.json" in text.replace("\\", "/"):
            offenders.append(path.name)
    assert not offenders, (
        f"still points at the untracked outside-the-repo copy: {offenders}"
    )


# =====================================================================
# The scope label
# =====================================================================

def test_the_file_carries_a_scope_block(results):
    assert "scope" in results, (
        "BENCHMARK_RESULTS.json claims a bare 100% with nothing saying "
        "what it was measured against"
    )


def test_the_scope_says_the_os_layer_is_mocked(results):
    scope = results["scope"]
    assert "mock" in scope["os_operations_executed"].lower(), scope
    assert scope["acceptance_evidence"] is False, scope


def test_the_scope_explicitly_denies_being_execution_proof(results):
    scope = results["scope"]
    what_not = scope["what_this_is_not"].lower()
    assert "not evidence of os execution" in what_not, scope
    assert "mock" in what_not, scope


def test_the_scope_says_what_it_actually_is(results):
    """Positive statement, not only a disclaimer."""
    what_is = _scope_text(results).lower()
    assert "understanding" in what_is or "routing" in what_is, results["scope"]


def test_the_scope_is_first_so_a_reader_meets_it_immediately():
    """Order survives the JSON round trip in Python 3.7+."""
    keys = list(json.loads(RESULTS.read_text(encoding="utf-8")).keys())
    assert keys[0] == "scope", keys


# =====================================================================
# Durability: regeneration must not strip the label
# =====================================================================

def test_the_renderer_always_emits_the_scope():
    """The property that makes the fix last.

    If the label were hand-written into the checked-in JSON, the next
    `python -m benchmark` would drop it and the file would go back to
    claiming a bare 100%.
    """
    from benchmark.report import render_json_report

    out = json.loads(render_json_report({"total": 1, "passed": 1}))
    assert "scope" in out, (
        "render_json_report dropped the scope block; regeneration would "
        "silently restore the dishonest bare 100%"
    )
    assert out["scope"]["acceptance_evidence"] is False
    assert out["total"] == 1, "aggregation must be preserved"


def test_the_scope_module_constant_is_self_consistent():
    from benchmark.report import BENCHMARK_SCOPE

    assert BENCHMARK_SCOPE["acceptance_evidence"] is False
    assert BENCHMARK_SCOPE["scope_label_version"] >= 1
    for key in ("what_this_is", "what_this_is_not", "os_operations_executed"):
        assert BENCHMARK_SCOPE.get(key), f"scope.{key} is empty"


def test_the_checked_in_file_matches_what_the_renderer_would_write():
    """The committed artifact must not drift from the tool's output."""
    from benchmark.report import render_json_report

    committed = json.loads(RESULTS.read_text(encoding="utf-8"))
    payload = {k: v for k, v in committed.items() if k != "scope"}
    regenerated = json.loads(render_json_report(payload))

    assert regenerated == committed, (
        "BENCHMARK_RESULTS.json has drifted from render_json_report's "
        "output; regenerate it rather than hand-editing"
    )


# =====================================================================
# The numbers were preserved, not invented
# =====================================================================

def test_the_numbers_are_unchanged(results):
    """11C relocates and labels; it must not quietly alter results."""
    assert results["total"] == 500, results["total"]
    assert results["passed"] == 500, results["passed"]
    assert results["failed"] == 0, results["failed"]
    assert results["pass_rate"] == 1.0, results["pass_rate"]
    assert isinstance(results["simulated_only"], int)


def test_by_metric_still_reports_every_metric(results):
    """11C was described as 'by_metric is routing-only'. It is not: it
    has 12 metrics including execution and verification. This test pins
    the real shape so the description cannot drift again."""
    metrics = results["by_metric"]
    assert len(metrics) >= 12, sorted(metrics)
    for name in (
        "understanding", "routing", "planning", "execution",
        "observation", "verification", "recovery",
    ):
        assert name in metrics, sorted(metrics)


def test_the_runner_really_is_mocked_so_the_label_is_true():
    """If the runner ever stops mocking, this label becomes wrong and
    should fail loudly rather than quietly understate coverage."""
    source = (BACKEND / "benchmark" / "runner.py").read_text(
        encoding="utf-8-sig"
    )
    tree = ast.parse(source)
    mocked = any(
        isinstance(node, ast.ClassDef) and "Mock" in node.name
        for node in ast.walk(tree)
    )
    assert mocked, (
        "benchmark/runner.py no longer defines a mock; revisit the scope "
        "label in BENCHMARK_RESULTS.json before regenerating it"
    )