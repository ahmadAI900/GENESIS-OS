"""The tripwire must see FIXTURE phases, and must still see the call phase.

Why this file exists
--------------------
The tripwire attached its capture frame from an autouse FUNCTION-scoped
fixture. That made two whole phases invisible, and invisibility is the
failure mode that matters, because a gate that stops seeing something
looks exactly like a gate with nothing to report:

  * pytest sets fixtures up HIGHEST SCOPE FIRST, so a module-scoped
    fixture was already built before any function-scoped autouse frame
    existed. A module-scoped fixture that builds a real `GenesisOS` --
    which is what `genesis_runtime` and `genesis` do -- ran its browser
    probe entirely outside the frame.
  * teardown runs LOWEST SCOPE FIRST, so a module- or session-scoped
    finalizer ran after the frame had been removed.

Both ends are now covered by hookwrappers around
`pytest_runtest_setup` and `pytest_runtest_teardown`.

Why every assertion here runs in a CHILD process
-----------------------------------------------
A file that is meant to fail must not be collected by an ordinary run,
and a fixture that must be observed being set up cannot be observed from
inside a test that is itself running under it. `tools/fixtures/`
holds the offenders; this file invokes them by explicit path in a child
pytest and asserts on what the child reported.

Every expected failure is asserted BY NAME, because "the run went red"
is not evidence of anything -- a syntax error in the offender file
would produce the same shape.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = BACKEND / "tools" / "fixtures"

# Not named test_*.py on purpose: a file that must fail may not be
# collected by an ordinary run, or the suite is permanently red for a
# reason nobody can explain. pytest still collects it when it is passed
# by explicit path, which is how the child process runs it.
PHASE_OFFENDERS = FIXTURES / "tripwire_phase_offenders_scratch.py"
CALL_OFFENDERS = FIXTURES / "tripwire_offenders_scratch.py"
TREE_OFFENDERS = FIXTURES / "tree_write_offenders_scratch.py"

pytestmark = pytest.mark.skipif(
    not PHASE_OFFENDERS.is_file() or not TREE_OFFENDERS.is_file(),
    reason="offender fixture files are missing",
)


def _run_child(*paths, extra=(), tb="no"):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *[str(p) for p in paths],
         "-q", "--no-header", "-p", "no:cacheprovider", f"--tb={tb}", "-rf",
         *extra],
        cwd=BACKEND, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout + proc.stderr


def _failed_nodeids(output: str) -> set:
    return {line.split(" ", 1)[1].split(" ")[0].strip()
            for line in output.splitlines() if line.startswith("FAILED ")}


# ----------------------------------------------------------------------
# Part 3.1 -- fixture phases
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def phase_run():
    return _run_child(PHASE_OFFENDERS)


# The three phases the brief names. Each must be reported as a FAILED
# carrying the offending test's own name.
@pytest.mark.parametrize("test_name,phase", [
    ("test_scratch_function_fixture_setup_is_caught", "function setup"),
    ("test_scratch_function_fixture_teardown_is_caught", "function teardown"),
    ("test_scratch_module_fixture_setup_is_caught", "module setup"),
])
def test_fixture_phase_violation_fails_by_name(phase_run, test_name, phase):
    rc, output = phase_run
    failed = _failed_nodeids(output)
    assert any(name.endswith("::" + test_name) for name in failed), (
        f"a {phase} capability violation did not fail {test_name}.\n"
        f"failed: {sorted(failed)}\n--- child output ---\n{output[-3000:]}")


def test_module_setup_is_attributed_to_the_first_requesting_test(phase_run):
    """The brief requires the requesting test, not merely some test.

    `test_scratch_module_fixture_setup_is_caught` is the ONLY test that
    requests `module_setup_offender`, so the two are the same assertion
    -- and it is stated separately because the attribution, not the
    detection, is the property that can silently regress.
    """
    rc, output = phase_run
    assert "::test_scratch_module_fixture_setup_is_caught" in output


def test_teardown_violation_is_reported_as_failed_not_error(phase_run):
    """A finding in a finalizer must not read as 'N passed, 1 error'.

    That shape is exactly how a test that quietly reached a browser gets
    missed. `_pytest.runner.pytest_report_teststatus` maps any failed
    setup/teardown report to ("error", "E", "ERROR"), so the plugin
    overrides it; this asserts the override is still in place.
    """
    rc, output = phase_run
    assert " error" not in output.replace("0 errors", ""), (
        "a fixture-phase violation was reported as an ERROR; it must be "
        "an ordinary FAILED\n--- child output ---\n"
        f"{output[-2500:]}")


def test_a_clean_test_in_the_same_module_still_passes(phase_run):
    """A tripwire that fails everything is not a tripwire."""
    rc, output = phase_run
    assert "test_scratch_clean_sibling_still_passes" not in \
        " ".join(_failed_nodeids(output)), (
        "the tripwire failed a test that reached no capability")


# ----------------------------------------------------------------------
# Part 3.1 regression: the original three call-phase offenders
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def call_run():
    # `--tb=short`, not `--tb=no`: the assertion below is that the
    # failure message NAMES what was reached, and the detail is the
    # traceback body. Suppressing it would make the test assert nothing.
    return _run_child(CALL_OFFENDERS, tb="short")


@pytest.mark.parametrize("test_name,needle", [
    ("test_scratch_non_loopback_network_is_caught", "203.0.113.1"),
    ("test_scratch_non_allowlisted_executable_is_caught", "hostname.exe"),
    ("test_scratch_ctypes_window_station_is_caught",
     "user32.GetForegroundWindow"),
])
def test_original_call_phase_offender_still_fails(call_run, test_name, needle):
    rc, output = call_run
    failed = _failed_nodeids(output)
    assert any(name.endswith("::" + test_name) for name in failed), (
        f"extending the tripwire to fixture phases stopped it catching "
        f"{test_name} in the call phase, which it always caught.\n"
        f"failed: {sorted(failed)}")
    assert needle in output, (
        f"the message for {test_name} no longer names {needle!r}")


# ----------------------------------------------------------------------
# Part 3.2 -- the product-tree write check
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def tree_run():
    return _run_child(TREE_OFFENDERS)


def test_relative_path_write_into_the_product_tree_fails_by_name(tree_run):
    """The `backend/file` reproduction.

    A test that writes a bare relative name with the process sitting in
    the product tree must be failed by name.
    """
    rc, output = tree_run
    failed = _failed_nodeids(output)
    assert any(name.endswith("::test_scratch_relative_write_from_backend_"
                             "is_caught") for name in failed), (
        f"a relative write into the product tree was not caught.\n"
        f"failed: {sorted(failed)}\n--- child output ---\n{output[-3000:]}")


def test_absolute_and_mkdir_writes_are_caught_too(tree_run):
    rc, output = tree_run
    failed = _failed_nodeids(output)
    for name in ("test_scratch_absolute_product_path_is_caught",
                 "test_scratch_mkdir_in_product_tree_is_caught"):
        assert any(f.endswith("::" + name) for f in failed), (
            f"{name} was not caught; an explicit path must be no "
            f"different from a relative one")


def test_writing_inside_the_workspace_is_not_a_violation(tree_run):
    """`workspace_root` is where filesystem tests are meant to write."""
    rc, output = tree_run
    failed = _failed_nodeids(output)
    assert not any("inside_product_tree" in f and
                   "relative_write_into" not in f for f in failed), (
        "a write inside the workspace root was reported as a violation")
    assert "test_scratch_relative_write_into_product_tree_is_caught" not in \
        " ".join(failed), (
            "a write under the workspace_root fixture was failed; the "
            "check must allow it")


def test_the_check_left_no_artefact_behind(tree_run):
    """A check that detects writes must not become one."""
    for name in ("c2_scratch_relative_write.txt", "c2_scratch_absolute_write.txt"):
        assert not (BACKEND / name).exists(), (
            f"{name} survived the scratch run")
    assert not (BACKEND / "c2_scratch_dir").exists()


# ----------------------------------------------------------------------
# The check itself must be auditable, or it is just a blacklist.
# ----------------------------------------------------------------------

def test_the_allowlist_is_declared_and_auditable():
    import tree_write_plugin as tw

    assert tw.ALLOWED_WRITES, (
        "no product-tree write is allowlisted. If the list is empty that "
        "may be correct, but it means nobody has checked: an exemption "
        "that appears without anyone noticing is a hole.")
    for path, reason in tw.ALLOWED_WRITES.items():
        assert reason and len(reason) > 40, (
            f"the exemption for {path} has no real reason. Every entry "
            f"must state WHY the write is allowed, the way "
            f"HARMLESS_EXECUTABLES in tiering_rules.py does.")
        assert tw.BACKEND in Path(path).parents or \
            Path(path) == tw.BACKEND, (
            f"{path} is not inside the product tree, so allowing it "
            f"grants nothing and hides a mistake in the allowlist")


def test_the_audit_log_exemption_names_both_the_file_and_its_directory():
    """The directory entry exists because of a real makedirs call.

    `approval_channel.py:118` calls `path.parent.mkdir(...)`, so
    WITHOUT the directory entry 23 tests in test_approval_channel.py
    were failed for an `os.makedirs` on `genesis_os/`. That is the
    measured behaviour, recorded here so the exemption cannot be
    dropped without the reason being noticed.
    """
    import tree_write_plugin as tw

    allowed = {str(p) for p in tw.ALLOWED_WRITES}
    assert str((tw.BACKEND / "genesis_os").resolve()) in allowed
    assert str((tw.BACKEND / "genesis_os" /
                "approval_audit.jsonl").resolve()) in allowed
    source = (tw.BACKEND / "genesis_os" /
              "approval_channel.py").read_text(encoding="utf-8")
    assert "path.parent.mkdir" in source, (
        "the exemption exists because approval_channel.py calls "
        "path.parent.mkdir; that call is gone, so the directory "
        "exemption should be re-examined")


def test_the_check_can_be_disabled_for_bisecting():
    import tree_write_plugin as tw

    assert "off" in tw.__doc__ or "--tree-writes=off" in str(tw.__doc__), (
        "the escape hatch is undocumented")
