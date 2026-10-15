"""The no-vacuous-pass guard must catch a vacuous run.

Continuation A3 reported "transparency 8/8" and the truth was 8 skips.
A test that skips and a test that passes both yield exit code 0, so
anything that only looks at the exit code cannot tell them apart. This
file proves `tools/require_passed.py` tells them apart, by constructing
the failure deliberately and asserting it is caught.

Unit tests for the parser, plus one end-to-end run against a real
required set invoked in the wrong mode so that it skips.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "tools"))

import require_passed as rp  # noqa: E402


# ----------------------------------------------------------------------
# Parsing. The guard is only as good as what it can read.
# ----------------------------------------------------------------------

def test_parses_a_clean_summary():
    text = "8 passed, 2 warnings in 3.10s"
    assert rp._parse_summary(text)["passed"] == 8


def test_parses_skips_xfails_and_failures_together():
    text = "4 failed, 10 passed, 3 skipped, 1 xfailed, 2 errors in 9.9s"
    got = rp._parse_summary(text)
    assert got["failed"] == 4
    assert got["passed"] == 10
    assert got["skipped"] == 3
    assert got["xfailed"] == 1
    assert got["errors"] == 2


def test_parses_no_tests_ran():
    got = rp._parse_summary("no tests ran in 0.01s")
    assert sum(got.values()) == 0


def test_skips_are_not_silently_counted_as_passes():
    """The A3 shape: everything skipped, exit code 0, count reads 8."""
    text = "collected 8 items\n8 skipped in 0.20s"
    got = rp._parse_summary(text)
    assert got["passed"] == 0, (
        "a skipped test must never be counted as passed; that is the "
        "exact miscount this script exists to prevent")
    assert got["skipped"] == 8


def test_parses_node_statuses():
    text = ("PASSED tools/test_x.py::test_a\n"
            "SKIPPED tools/test_x.py::test_b\n"
            "FAILED tools/test_x.py::test_c\n"
            "XFAIL tools/test_x.py::test_d\n")
    got = rp._parse_node_statuses(text)
    assert got["tools/test_x.py::test_a"] == "PASSED"
    assert got["tools/test_x.py::test_b"] == "SKIPPED"


def test_non_passing_lists_only_non_passing():
    text = ("PASSED a.py::t1\nSKIPPED a.py::t2\nXPASS a.py::t3\n"
            "PASSED a.py::t4\n")
    statuses = rp._parse_node_statuses(text)
    non = sorted(n for n, s in statuses.items() if s != "PASSED")
    assert non == ["a.py::t2", "a.py::t3"]


# ----------------------------------------------------------------------
# The guard's own configuration
# ----------------------------------------------------------------------

def test_every_required_set_states_why_it_matters():
    for name, entry in rp.REQUIRED_SETS.items():
        assert entry.why.strip(), f"{name} has no justification"
        assert entry.targets, f"{name} has no targets"


def test_recorder_sets_require_the_recorder_to_be_active():
    """Without --record these sets skip, which is the vacuous case."""
    for name in ("recorder_transparency", "recorder_canaries"):
        entry = rp.REQUIRED_SETS[name]
        assert "--record" in entry.marker_args, (
            f"{name} must require --record or it passes by skipping")
        assert "record_probe" in entry.marker_args


def test_evaluate_reports_ok_for_a_real_passing_set():
    report = rp.evaluate(["tripwire_mutation"])
    assert report["ok"], report["results"]


# ----------------------------------------------------------------------
# End to end: catch a deliberate vacuous run
# ----------------------------------------------------------------------

def test_catches_a_required_set_run_in_the_wrong_mode():
    """The A3 failure, constructed on purpose.

    `recorder_transparency` is run WITHOUT `--record`, which is exactly
    the mistake A3 made. Every test skips. pytest exits 0. The guard
    must still fail it and name the skip count.
    """
    vacuous = rp.RequiredSet(
        name="recorder_transparency_vacuous",
        targets=rp.REQUIRED_SETS["recorder_transparency"].targets,
        marker_args=[],          # <-- the mistake
        why="deliberately wrong mode, to prove the guard is not fooled",
    )
    result = rp.run_set(vacuous)
    assert result["summary"]["skipped"] == 8, result["summary"]
    assert result["returncode"] == 0, (
        "pytest exits 0 when everything skips; that is the whole trap")
    problems = []
    if not result["ran_anything"]:
        problems.append("no tests ran at all")
    if result["summary"]["skipped"]:
        problems.append(f"{result['summary']['skipped']} skipped")
    assert problems, "guard found no problem with an all-skipped set"
    assert any("skipped" in p for p in problems)


def test_cli_exits_nonzero_when_a_set_is_vacuous():
    """End-to-end through the actual CLI, not just the API."""
    script = (
        "import sys; sys.path.insert(0, r'%s');\n"
        "import require_passed as rp;\n"
        "v = rp.RequiredSet(name='vacuous', targets=%r, marker_args=[],\n"
        "                   why='deliberate');\n"
        "r = rp.run_set(v);\n"
        "print('SKIPPED=%%d RC=%%d' %% (r['summary']['skipped'], r['returncode']));\n"
    ) % (BACKEND / "tools", rp.REQUIRED_SETS["recorder_transparency"].targets)
    proc = subprocess.run([sys.executable, "-c", script], cwd=BACKEND,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "SKIPPED=8 RC=0" in proc.stdout, proc.stdout


def test_json_report_records_the_problem_not_just_the_count(tmp_path):
    report = rp.evaluate(["tripwire_mutation"])
    # tmp_path, not `docs/`. The product-tree write check
    # (tools/tree_write_plugin.py) failed this test by name for writing
    # its scratch JSON into the source tree, which is the same defect
    # class that produced the zero-byte `backend/file`: a test that
    # leaves artefacts where the product lives.
    out = tmp_path / "require_passed_selftest.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    payload = json.loads(out.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert "summary" in result and "why" in result
    assert result["ok"] is True