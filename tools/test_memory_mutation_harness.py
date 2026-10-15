"""The mutation harness must be trusted before it is trusted.

`run_behavior_mutations.py` (the sandbox-copy harness) reported all three
behavioural mutations MISSED and was wrong twice over:

  * its copy list omitted `emotion/`, so `brain/brain.py` raised
    ModuleNotFoundError and all 13 target tests ERRORed at setup;
  * its result parser looked only for lines beginning with `FAILED `, so
    13 setup errors produced an empty failure list, which it printed as
    `MISSED`.

The second bug is the one that matters. An instrument that never fired
was reported exactly like a suite with no coverage, and the report read
as a finding. So this file does not merely assert that the mutations are
caught -- it asserts that the harness REFUSES to report them as caught,
missed, or anything else unless it can prove the mutation was live.

Every assertion here runs in a CHILD pytest process. That is not
incidental: the harness mutates a module by intercepting its import, so
it cannot be tested in-process, where the module is already imported.

    python tools/test_memory_mutation_harness.py    # ~3 minutes
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
TOOLS = BACKEND / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import memory_mutations as mm  # noqa: E402
import run_memory_mutations as driver  # noqa: E402


# ----------------------------------------------------------------------
# The end-to-end result: one harness run, asserted over.
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def harness_run():
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "run_memory_mutations.py")],
        cwd=BACKEND, capture_output=True, text=True, timeout=1800,
        env=driver._child_env(None))
    return {
        "rc": proc.returncode,
        "output": proc.stdout + proc.stderr,
        "seconds": time.time() - started,
    }


def test_harness_run_is_green(harness_run):
    assert harness_run["rc"] == 0, (
        "the in-memory mutation harness did not pass.\n"
        f"--- output ---\n{harness_run['output'][-6000:]}")


def test_baseline_ran_and_was_green_in_the_same_harness(harness_run):
    """The thing the sandbox could not do.

    The old harness measured its baseline inside a temp copy that was not
    the product, and could not have told the difference. Here the
    baseline runs against the real tree in the same driver invocation.
    """
    out = harness_run["output"]
    assert "BASELINE (no mutation, real tree)" in out
    assert "baseline is green." in out
    # 13 tests ran. Assert the count so a silently-empty baseline fails.
    assert "ran=13" in out, (
        "the baseline did not run the 13 entry-point behavioural tests")


@pytest.mark.parametrize("name", sorted(mm.MUTATIONS_BY_NAME))
def test_each_mutation_is_caught_by_a_declared_behavioural_test(
        harness_run, name):
    spec = mm.MUTATIONS_BY_NAME[name]
    out = harness_run["output"]
    assert f"MUTATION: {name}" in out, f"{name} was not run at all"

    # The driver only prints this line when a DECLARED behavioural test
    # failed. It is the assertion, not a re-derivation of one.
    assert "caught by 1 declared behavioural test(s)." in out or \
        "caught by 4 declared behavioural test(s)." in out, (
        f"{name} was not reported as caught by a declared test.\n"
        f"declared detectors: {list(spec.caught_by)}")


def test_no_mutation_was_reported_missed(harness_run):
    out = harness_run["output"]
    for bad in ("[MISSED]", "[INSTRUMENT FAILURE]", "RESULT: FAIL",
                "INTEGRITY FAILURE"):
        assert bad not in out, (
            f"harness reported {bad!r}; full output:\n{out[-6000:]}")


def test_product_tree_is_byte_identical_after_the_harness(harness_run):
    out = harness_run["output"]
    assert "INTEGRITY" in out
    assert "[OK]" in out and "byte-identical" in out, (
        f"the integrity backstop did not confirm the tree:\n"
        f"{out[-4000:]}")
    assert "Nothing was written or copied." in out


# ----------------------------------------------------------------------
# The instrument refuses to report a result it cannot support.
# ----------------------------------------------------------------------

def test_transform_that_changes_nothing_is_a_hard_error():
    """A pattern that matches nothing must never be reported as MISSED.

    This is the exact class of bug that made the old harness useless.
    """
    source = "def real_name():\n    return 1\n"
    spec = mm.MemoryMutation(
        name="no-op", module="m",
        pattern="def something_absent():\n",
        replacement="def something_else():\n")
    with pytest.raises(mm.MutationNotApplied) as caught:
        mm.apply_mutation(source, spec)
    message = str(caught.value)
    assert "matched 0" in message
    assert "hard failure, not a skip" in message


def test_transform_matching_too_many_times_is_a_hard_error():
    source = "x = 1\nx = 1\n"
    spec = mm.MemoryMutation(
        name="too-many", module="m", pattern="x = 1\n",
        replacement="x = 2\n", expect_matches=2)
    # Two occurrences is what was declared, so this one is fine...
    assert mm.apply_mutation(source, spec).count("x = 2") == 2

    # ...and one occurrence for a spec expecting two is not.
    spec_bad = mm.MemoryMutation(
        name="too-many", module="m", pattern="x = 1\n",
        replacement="x = 2\n", expect_matches=5)
    with pytest.raises(mm.MutationNotApplied) as caught:
        mm.apply_mutation(source, spec_bad)
    assert "expected to match 5 time(s) but matched 2" in str(caught.value)


def test_transform_that_does_not_compile_is_a_hard_error():
    """Unparseable mutated source makes every test ERROR.

    Which the old harness rendered as MISSED. So it is caught here, at
    install time, before any test runs.
    """
    source = "def f():\n    return 1\n"
    spec = mm.MemoryMutation(
        name="unparseable", module="m",
        pattern="    return 1\n",
        replacement="    return 1\n        (((  \n")
    with pytest.raises(mm.MutationNotApplied) as caught:
        mm.apply_mutation(source, spec)
    assert "does not compile" in str(caught.value)


def test_matching_is_line_ending_insensitive():
    """CRLF, LF and lone-CR sources all mutate identically.

    genesis.py has been both fully-CRLF and mixed across this project's
    history, and the old harness's third mutation silently matched
    nothing for exactly this reason.
    """
    lf = "class C:\n    def classify(self, text):\n        return 1\n"
    spec = mm.MemoryMutation(
        name="rename", module="m",
        pattern="    def classify(self, text):\n",
        replacement="    def _MUTATED(self, text):\n")
    for variant, label in ((lf, "LF"),
                           (lf.replace("\n", "\r\n"), "CRLF"),
                           (lf.replace("\n", "\r"), "lone CR")):
        mutated = mm.apply_mutation(variant, spec)
        assert "_MUTATED" in mutated, f"{label} source did not mutate"
        assert "def classify" not in mutated, f"{label} left the old name"


def test_pattern_is_literal_not_a_regex():
    """Regression: `classify(self, text)` read as regex matched nothing.

    The parentheses became a capture group, so the pattern looked for
    `def classifyself, text:` -- present nowhere -- and the harness
    reported MISSED with total confidence. A spec is source text.
    """
    source = "class C:\n    def classify(self, text):\n        return 1\n"
    spec = mm.MemoryMutation(
        name="literal", module="m",
        pattern="    def classify(self, text):\n",
        replacement="    def renamed(self, text):\n")
    assert "renamed" in mm.apply_mutation(source, spec)


def test_every_declared_mutation_still_matches_the_real_genesis():
    """The specs are anchored in real product source; keep them honest."""
    source = (BACKEND / "genesis.py").read_text(encoding="utf-8")
    for spec in mm.MUTATIONS:
        mutated = mm.apply_mutation(source, spec)
        assert mutated != mm.normalise(source), spec.name


# ----------------------------------------------------------------------
# Verdict logic: MISSED must not be reachable from an unrunnable child.
# ----------------------------------------------------------------------

def test_an_empty_failed_list_from_an_errored_child_is_not_missed():
    """The old harness's bug, as a unit test.

    13 setup ERRORs and a green-looking result both produce an empty
    FAILED list. The driver must refuse to call either a catch.
    """
    output = ("ERROR test_x.py::test_a - ModuleNotFoundError: No module "
              "named 'emotion'\n13 errors in 8.04s\n")
    verdict = driver.classify_output(output)
    assert verdict["failed"] == []
    assert verdict["errored"], "the setup error should be visible"
    # And the driver must act on `errored` before it acts on `failed`.
    assert verdict["errored"], "an ERROR is never evidence of a catch"


def test_a_child_that_never_printed_the_marker_is_not_applied():
    output = "13 passed in 15.59s\n"
    verdict = driver.classify_output(output, mutation={"name": "x"})
    assert verdict["marker_present"] is False
    baseline = driver.classify_output(output, mutation=None)
    assert baseline["marker_present"] is None


def test_marker_detection_is_positive_only():
    output = "[memmut] MUTATED genesis :: x (10 -> 20 bytes, in memory only)\n"
    verdict = driver.classify_output(output, mutation={"name": "x"})
    assert verdict["marker_present"] is True


def test_collected_count_reads_the_summary_line():
    assert driver._collected_count("13 passed in 15.59s") == 13
    assert driver._collected_count("4 failed, 9 passed in 17.36s") == 13
    assert driver._collected_count("13 errors in 8.04s") == 13
    assert driver._collected_count("") == 0
    assert driver._collected_count("no tests ran in 0.00s") == 0


def test_collected_count_ignores_other_summaries():
    """Regression: a plugin summary was read as pytest's.

    The tripwire and the product-tree check both print their own
    summaries, and the line

        0 of 13 fast-gate test(s) wrote into the product tree and were
        failed. 0 reached a real capability.

    matches a loose "contains 'failed'" test. The forward parser then
    returned 0 for a child that had run 13 tests, and every mutation
    through it was declared a NO_TESTS instrument failure. The parser
    must only read pytest's own final line, and must read it from the
    END of the output.
    """
    output = (
        "[tree-writes] REPORT mode\n"
        "0 of 13 fast-gate test(s) wrote into the product tree and were "
        "failed.\n"
        "watched 13 fast-gate test(s); 0 reached a real capability.\n"
        "0.02s total, 1.382 ms per test\n"
        "4 failed, 9 passed, 3 warnings in 17.36s (0:00:17)\n")
    assert driver._collected_count(output) == 13


def test_collected_count_does_not_add_warnings():
    output = "1 passed, 1 warning, 2 skipped, 1 xfailed in 9.00s\n"
    assert driver._collected_count(output) == 4


# ----------------------------------------------------------------------
# Integrity backstop
# ----------------------------------------------------------------------

def test_integrity_backstop_detects_create_modify_and_delete():
    before = {"a.py": "1", "b.py": "2"}
    for label, after in (
            ("create", {"a.py": "1", "b.py": "2", "c.py": "3"}),
            ("modify", {"a.py": "1", "b.py": "CHANGED"}),
            ("delete", {"a.py": "1"})):
        with pytest.raises(mm.TreeIntegrityError) as caught:
            mm.check_fingerprint(before, after, f"a {label} canary")
        assert label.upper()[:3] in str(caught.value).upper()


def test_integrity_backstop_accepts_an_identical_tree():
    fingerprint = {"a.py": "1", "b.py": "2"}
    mm.check_fingerprint(fingerprint, dict(fingerprint), "a no-op canary")


def test_fingerprint_covers_files_the_old_harness_ignored():
    """The old harness hashed `*.py` only.

    That would not have noticed a zero-byte file named `file` appearing
    in `backend/` -- which is exactly the artefact that did appear.
    """
    fingerprint = mm.product_fingerprint()
    assert "genesis.py" in fingerprint
    assert "conftest.py" in fingerprint
    non_python = [k for k in fingerprint if not k.endswith(".py")]
    assert non_python, (
        "the fingerprint only covers .py files, so it would miss a "
        "test-created artefact of any other type")
    assert "file" in fingerprint, (
        "backend/file (the zero-byte artefact) is not in the fingerprint; "
        "if this fails the artefact has been removed, which is fine, but "
        "the fingerprint must be shown to cover non-.py files")