"""Guards for the three tooling bug classes that cost B1 real time.

B1 lost hours to each of these, and each one is silent:

1. **Duplicate pytest hook.** `conftest.py` briefly defined
   `pytest_collection_modifyitems` twice. Python binds only the last, so
   the first never ran and a fixture sat in the file looking attached.
2. **Nested pytest without targets.** `pytest` with no path arguments
   collects the entire rootdir. A "cheap" test passing an empty target
   list ran the whole suite from inside itself: 25 minutes became four
   hours, and the nested runs corrupted the probes they measured.
3. **Silent mutation skips.** A mutation pattern that matched nothing was
   reported as SKIP, which reads like an honest result rather than an
   instrument that never fired.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "tools"))

import run_behavior_mutations as rbm  # noqa: E402

PYTEST_HOOKS = {
    "pytest_addoption", "pytest_configure", "pytest_unconfigure",
    "pytest_collection_modifyitems", "pytest_collection_finish",
    "pytest_runtest_setup", "pytest_runtest_call", "pytest_runtest_teardown",
    "pytest_sessionstart", "pytest_sessionfinish", "pytest_terminal_summary",
    "pytest_report_header", "pytest_runtest_logstart", "pytest_runtest_logfinish",
}


# ----------------------------------------------------------------------
# 1. Duplicate hook guard
# ----------------------------------------------------------------------
def _top_level_defs(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
    return names


@pytest.mark.parametrize("conftest", ["conftest.py"])
def test_conftest_defines_each_pytest_hook_exactly_once(conftest):
    """The B1 bug, as a permanent guard.

    A second definition silently replaces the first. Nothing crashes and
    nothing warns -- the fixture just quietly never attaches.
    """
    names = _top_level_defs(BACKEND / conftest)
    hooks = [n for n in names if n in PYTEST_HOOKS]
    duplicates = sorted({h for h in hooks if hooks.count(h) > 1})
    assert not duplicates, (
        f"{conftest} defines these pytest hooks more than once: "
        f"{duplicates}. Python binds only the last definition, so the "
        f"earlier one never runs.")


def test_the_duplicate_hook_guard_itself_fires_on_a_synthetic_duplicate(tmp_path):
    """Prove the check can fail, with a scratch file that does duplicate."""
    scratch = tmp_path / "conftest.py"
    scratch.write_text(
        "def pytest_configure(config):\n    pass\n"
        "\n"
        "def pytest_collection_modifyitems(config, items):\n    pass\n"
        "\n"
        "def pytest_collection_modifyitems(config, items):\n    pass\n",
        encoding="utf-8")
    names = _top_level_defs(scratch)
    hooks = [n for n in names if n in PYTEST_HOOKS]
    duplicates = sorted({h for h in hooks if hooks.count(h) > 1})
    assert duplicates == ["pytest_collection_modifyitems"], duplicates


def test_no_duplicate_top_level_definitions_in_conftest():
    """Broader than hooks: any duplicated top-level def is suspect."""
    names = _top_level_defs(BACKEND / "conftest.py")
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"duplicate top-level definitions: {duplicates}"


# ----------------------------------------------------------------------
# 2. Nested-pytest guard
# ----------------------------------------------------------------------
def _nested_pytest_calls(tree):
    """Every subprocess/pytest invocation that runs pytest."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            dotted = ""
            if isinstance(func, ast.Attribute):
                parts = []
                cur = func
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                dotted = ".".join(reversed(parts))
            elif isinstance(func, ast.Name):
                dotted = func.id
            if dotted in ("pytest.main", "pytest.main"):
                hits.append((node, dotted))
            elif dotted in ("subprocess.run", "subprocess.Popen",
                            "subprocess.check_call", "subprocess.call"):
                args = node.args
                argv = []
                if args and isinstance(args[0], (ast.List, ast.Tuple)):
                    argv = [a.value for a in args[0].elts
                            if isinstance(a, ast.Constant)]
                elif len(args) > 1:
                    argv = [a.value for a in args[1].elts
                            if isinstance(a, ast.Constant)]
                if any(isinstance(v, str) and "pytest" in v for v in argv):
                    hits.append((node, dotted))
    return hits


def _pos_arg_strings(node):
    """Literal string positional arguments, plus a has-non-literal flag.

    A non-literal argument (`str(OFFENDERS)`) IS a target; only a
    wholly absent or wholly-flag argument list means "no target". Treating
    every non-Constant as "no target" flagged a correct caller.
    """
    literals = []
    saw_non_literal = False
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            literals.append(arg.value)
        elif isinstance(arg, (ast.List, ast.Tuple)):
            # An argv list. Only its STRING elements can be literal
            # targets, and argv[0] is always the interpreter
            # (`sys.executable`), never a target. A non-literal at any
            # index >= 1 is almost certainly a computed path -- e.g.
            # `subprocess.run([sys.executable, "-m", "pytest", str(F)])`
            # -- so it counts as a target.
            for index, element in enumerate(arg.elts):
                if isinstance(element, ast.Constant) and isinstance(
                        element.value, str):
                    literals.append(element.value)
                elif index >= 1:
                    saw_non_literal = True
        else:
            # A bare non-literal positional, e.g. `pytest.main(path)`
            # where `path` is a variable: that IS a target.
            saw_non_literal = True
    return literals, saw_non_literal


def _has_explicit_target(literals, saw_non_literal):
    if saw_non_literal:
        return True
    return any(v.endswith(".py") or v.endswith("::") or v == "."
               or v.endswith("/") for v in literals)


# Pre-existing offenders, recorded rather than fixed.
#
# B2 may not edit a pre-existing test body, and these three call
# `pytest.main()` without explicit targets. The guard therefore
# BASELINES them: a new offender fails, an old one is reported. Same
# shape as the ruff baseline.
NESTED_PYTEST_BASELINE = {
    # Pre-existing: `pytest.main()` with no path argument, so pytest
    # collects the whole rootdir. B2 may not edit a pre-existing test
    # body, so these are recorded, not fixed. A NEW offender fails.
    "test_context_resolver.py",
    "test_phase2_deferred_items.py",
    "test_unified_executor.py",
}


def _nested_pytest_offenders():
    offenders = set()
    for path in BACKEND.rglob("test_*.py"):
        if any(part in {".venv", "__pycache__", ".pytest_cache"}
               for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            pytest.fail(
                f"{path.relative_to(BACKEND)} is not valid UTF-8: {error}. "
                f"The nested-pytest guard cannot inspect it; fix the file "
                f"encoding instead of skipping it.",
                pytrace=False,
            )
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        for node, _dotted in _nested_pytest_calls(tree):
            literals, non_literal = _pos_arg_strings(node)
            if not _has_explicit_target(literals, non_literal):
                offenders.add(str(path.relative_to(BACKEND)))
    return offenders


def test_no_new_test_file_spawns_pytest_without_explicit_targets():
    """A nested pytest with no path arguments runs the entire suite."""
    offenders = _nested_pytest_offenders()
    new = sorted(offenders - NESTED_PYTEST_BASELINE)
    assert not new, (
        "these run pytest with no explicit target, so pytest collects the "
        "whole rootdir:\n  " + "\n  ".join(new) +
        f"\n(pre-existing and baselined, not fixable here: "
        f"{sorted(offenders & NESTED_PYTEST_BASELINE)})")


def test_nested_pytest_baseline_is_still_present():
    """If the baselined files vanish, the baseline should be pruned."""
    offenders = _nested_pytest_offenders()
    stale = sorted(NESTED_PYTEST_BASELINE - offenders)
    assert not stale, (
        f"nested-pytest baseline lists files that no longer offend: {stale}. "
        f"Prune them, or the baseline stops describing reality.")


def test_nested_pytest_guard_fires_on_a_scratch_offender(tmp_path):
    """Prove the guard can fail."""
    scratch = tmp_path / "test_scratch_nested.py"
    scratch.write_text(
        "import subprocess, sys\n"
        "\n"
        "def test_bad():\n"
        "    subprocess.run([sys.executable, '-m', 'pytest'], check=False)\n",
        encoding="utf-8")
    tree = ast.parse(scratch.read_text(encoding="utf-8"))
    hits = _nested_pytest_calls(tree)
    assert hits, "the guard did not even find the nested pytest call"
    node, _ = hits[0]
    literals, non_literal = _pos_arg_strings(node)
    assert not _has_explicit_target(literals, non_literal), (
        "scratch offender should have no explicit target")


def test_nested_pytest_guard_names_a_non_utf8_test_file(monkeypatch, tmp_path):
    """A cp1252 test file must be named, not silently skipped or crashed on."""
    monkeypatch.setattr(sys.modules[__name__], "BACKEND", tmp_path)
    bad = tmp_path / "test_bad.py"
    bad.write_bytes(b"# caf\xe9\n")

    with pytest.raises(pytest.fail.Exception) as caught:
        _nested_pytest_offenders()

    message = str(caught.value)
    assert "test_bad.py" in message, message
    assert "UTF-8" in message, message


# ----------------------------------------------------------------------
# 3. Mutation harness: no silent skips
# ----------------------------------------------------------------------

def test_apply_mutation_raises_when_the_pattern_cannot_match():
    """The B1 CRLF bug: a pattern that matches nothing reported as SKIP."""
    with pytest.raises(rbm.MutationNotApplied):
        rbm.apply_mutation("def f():\n    pass\n",
                            r"def this_pattern_cannot_exist_xyz\(.*\):",
                            r"def other():")


def test_apply_mutation_normalises_line_endings_for_matching():
    """genesis.py's run_level3 block is CRLF; an LF-only pattern misses."""
    crlf = "    def run_level3(\r\n        self,\r\n    ):\r\n"
    mutated = rbm.apply_mutation(
        crlf,
        r"(    def run_level3\(\n        self,\n    \):\n)",
        "\\1        pass\n")
    assert "pass" in mutated, mutated
    # And it must NOT rewrite the endings of the lines it did not touch.
    assert mutated.startswith("    def run_level3(\r\n"), repr(mutated)


def test_normalise_newlines_reports_the_detected_convention():
    normalised, eol = rbm.normalise_newlines("a\r\nb\r\n")
    assert normalised == "a\nb\n"
    assert eol == "\r\n"
    normalised, eol = rbm.normalise_newlines("a\nb\n")
    assert normalised == "a\nb\n"
    assert eol == "\n"


def test_real_mutations_all_apply_to_the_real_source():
    """Every shipped mutation must still apply, or the harness is blind."""
    source = (rbm.GENESIS).read_bytes().decode("utf-8")
    for name, pattern, replacement in rbm.MUTATIONS:
        try:
            rbm.apply_mutation(source, pattern, replacement)
        except rbm.MutationNotApplied as error:
            pytest.fail(f"{name}: {error}")


def test_the_shipped_mutations_are_three_and_all_named():
    assert len(rbm.MUTATIONS) == 3, rbm.MUTATIONS
    for name, pattern, replacement in rbm.MUTATIONS:
        assert name.strip(), "a mutation with no name is unreportable"
        assert pattern and replacement, name