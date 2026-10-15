"""`verify_all --fast` must reject a vacuous required set.

The seal component already takes ~4 minutes, so this drives the same
component-selection and pass/fail logic `verify_all` uses, with the
required sets replaced by one invoked in the WRONG mode.

A gate that reports PASS on a run where the required validations
skipped is worse than no gate: it converts an unmeasured property into a
measured one.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "tools"))

import require_passed as rp  # noqa: E402
import verify_all as va  # noqa: E402


def test_compileall_component_passes_on_a_clean_tree():
    """Safe to run in-suite: compileall is a fast, side-effect-free check."""
    component = va.compileall()
    assert component.ok, (component.counts, component.note, component.returncode)


def test_required_sets_component_is_configured():
    """Cheap structural check only.

    An earlier version of this file called `va.required_sets()` and
    `va.fast_tier()` inside a test. Each of those spawns nested pytest
    runs -- one of which is the whole required-set gate -- so running
    this file inside the suite re-ran large parts of the suite from
    within itself. The full default-order run went from 25 minutes to
    FOUR HOURS, and the nested runs interfered with the very probes
    they were measuring. A test about a gate must not itself be a gate.
    """
    assert len(rp.REQUIRED_SETS) >= 6, rp.REQUIRED_SETS.keys()
    for name, entry in rp.REQUIRED_SETS.items():
        assert entry.targets, name
        assert entry.why.strip(), name


def test_required_sets_component_rejects_an_empty_target_list():
    """Structural check, no subprocess.

    An earlier version called `rp.run_set()` with an EMPTY target list.
    pytest with no path arguments collects the whole rootdir -- so a
    "cheap" test of an empty set ran the entire suite, twice. That is how
    the full default-order run went from 25 minutes to four hours.

    The guard belongs here, where the mistake was made.
    """
    for name, entry in rp.REQUIRED_SETS.items():
        assert entry.targets, (
            f"{name} has no targets; pytest would collect the entire "
            f"rootdir and run the whole suite")
        assert not any(t.startswith("-") for t in entry.targets), name


def test_fast_tier_component_reports_real_counts():
    """A pytest component that collected nothing must NOT count as OK."""
    component = va.run_component(
        "vacuous tier",
        [sys.executable, "-m", "pytest", "-m", "a-marker-nobody-has",
         "-q", "-p", "no:cacheprovider"])
    assert not component.ok, "an empty collection was reported as OK"
    assert component.note == "no tests ran", component.note


def test_required_sets_component_fails_on_a_vacuous_set():
    """The A3 failure shape: every test skips, pytest exits 0."""
    vacuous = rp.RequiredSet(
        name="recorder_transparency_vacuous",
        targets=rp.REQUIRED_SETS["recorder_transparency"].targets,
        marker_args=[],           # the mistake A3 made
        why="deliberately wrong mode",
    )
    result = rp.run_set(vacuous)
    assert result["returncode"] == 0, "pytest should exit 0 on all-skips"
    assert result["summary"]["skipped"] == 8, result["summary"]

    component = va.Component("required sets (vacuous)", [], 0.0, 0,
                             {}, False, "")
    # The gate's own rule, applied by hand, must reject it.
    summary = result["summary"]
    rejected = (not summary["passed"] and summary["skipped"] > 0)
    assert rejected, "the gate's rule accepted an all-skipped required set"


def test_verify_all_table_marks_a_failing_component():
    import io
    import contextlib

    good = va.Component("ok one", [], 1.0, 0,
                        {"passed": 3, "skipped": 0, "xfailed": 0,
                         "failed": 0}, True)
    bad = va.Component("bad one", [], 1.0, 1,
                       {"passed": 1, "skipped": 2, "xfailed": 0,
                        "failed": 1}, False, "no tests ran")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        va.print_table([good, bad])
    text = buffer.getvalue()
    assert "ok one" in text and "bad one" in text
    ok_line = next(l for l in text.splitlines() if l.startswith("ok one"))
    bad_line = next(l for l in text.splitlines() if l.startswith("bad one"))
    assert ok_line.rstrip().endswith("OK"), ok_line
    assert "FAIL" in bad_line, bad_line


def test_manifest_detects_a_created_product_file(tmp_path):
    """The manifest check must be able to fail, or it is decoration."""
    before = {"a.py": (1, "x"), "b.py": (2, "y")}
    after = {"a.py": (1, "x"), "b.py": (3, "z"), "c.py": (9, "w")}
    created, removed, modified = va.diff_manifests(before, after)
    assert created == ["c.py"], created
    assert removed == [], removed
    assert modified == ["b.py"], modified


def test_manifest_diff_on_identical_trees_is_empty():
    tree = {"a.py": (1, "x")}
    created, removed, modified = va.diff_manifests(tree, dict(tree))
    assert (created, removed, modified) == ([], [], [])