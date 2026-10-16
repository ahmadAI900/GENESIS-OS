"""Item 6A -- the passive extraction island must stay consciously unwired.

`memory/long_term_memory.py` contains a complete but unreachable
extraction path:

    learn_from_turn() -> extract_deterministic()
                      -> extract_with_ai() -> looks_personal()

Nothing in the product calls it. Facts reach memory only through the
explicit "remember X" command (handle_command -> upsert_fact).

The island is RETAINED deliberately (Item 5D) rather than deleted, so
the capability is available. Wiring it would be a privacy decision --
it would store facts the user never asked Genesis to remember -- not a
bug fix.

These tests pin that honesty:

  * the docstring no longer advertises an ambient pipeline that does
    not run;
  * the island is reachable only from within its own file;
  * therefore, if someone later wires it, these tests FAIL and the
    change has to be a deliberate one.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent
ISLAND_FILE = BACKEND / "memory" / "long_term_memory.py"

# The four functions that form the closed extraction island.
ISLAND = (
    "learn_from_turn",
    "extract_deterministic",
    "extract_with_ai",
    "looks_personal",
)


def _product_python_files():
    """Every product .py under the backend, excluding caches."""
    skip_dirs = {"__pycache__", ".git", ".venv", "node_modules", "backups"}
    for path in BACKEND.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path


def _calls_in(path: Path, names):
    """AST names called in this file (attribute calls included).

    Fails CLOSED on an unparsable file: a SyntaxError here used to be
    swallowed into "no calls found", which silently disarmed the guard
    for exactly the file most likely to hold new wiring code. A file we
    cannot read is treated as suspicious rather than clean.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set(names)  # unreadable -> assume the worst

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        pytest.fail(
            f"cannot parse {path}, so the island guard cannot prove this "
            f"file is clean: {exc}. The guard must never pass on a file "
            "it could not read."
        )

    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called.add(func.id)
        elif isinstance(func, ast.Attribute):
            called.add(func.attr)
    return called & set(names)


# ----------------------------------------------------------------------
# The guard: nothing outside the island's own file may call into it
# ----------------------------------------------------------------------
@pytest.mark.parametrize("name", ISLAND)
def test_no_product_module_calls_the_island(name):
    """The guard itself.

    If a future change wires the island, this fails -- which is the
    point. Wiring it must be deliberate and must update this file.
    """
    offenders = []
    for path in _product_python_files():
        if path.resolve() == ISLAND_FILE.resolve():
            continue
        # The guard test itself names these functions; it cannot be a
        # real caller.
        if path.resolve() == Path(__file__).resolve():
            continue
        if name in _calls_in(path, (name,)):
            offenders.append(str(path.relative_to(BACKEND)))

    assert not offenders, (
        f"{name!r} is now called from outside memory/long_term_memory.py "
        f"by: {offenders}. The passive extraction island was wired. That is "
        "a PRIVACY decision -- Genesis would begin storing facts the user "
        "never asked it to remember -- so it must be behind an explicit "
        "opt-in memory mode and this guard updated deliberately."
    )


def test_the_island_is_still_present_and_complete():
    """Retained, not deleted -- so it stays available to wire later."""
    source = ISLAND_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    }
    for name in ISLAND:
        assert name in defined, f"{name} was deleted from the island"


def test_learn_from_turn_calls_the_other_two():
    """The island is internally coherent, not a pile of loose functions."""
    assert {"extract_deterministic", "extract_with_ai"} <= _calls_in(
        ISLAND_FILE, ("extract_deterministic", "extract_with_ai")
    )
    assert "looks_personal" in _calls_in(ISLAND_FILE, ("looks_personal",))


def test_the_explicit_memory_path_is_the_one_that_runs():
    """`handle_command` -> `upsert_fact` is how facts actually arrive."""
    assert "upsert_fact" in _calls_in(
        ISLAND_FILE, ("upsert_fact",)
    ), "the explicit 'remember X' path must still call upsert_fact"


# ----------------------------------------------------------------------
# The docstring must not claim a pipeline that does not run
# ----------------------------------------------------------------------
def _module_docstring() -> str:
    return ast.get_docstring(
        ast.parse(ISLAND_FILE.read_text(encoding="utf-8"))
    ) or ""


def test_the_docstring_does_not_claim_the_ambient_pipeline():
    """It previously opened with an extraction diagram that is not wired."""
    doc = _module_docstring().lower()
    assert "fact extraction (deterministic + ai)" not in doc, (
        "the docstring still advertises 'conversation -> fact extraction "
        "(deterministic + AI) -> long_term_memory.json'; no ambient "
        "extraction runs in the product"
    )


def test_the_docstring_states_the_island_is_not_wired():
    doc = _module_docstring().lower()
    assert "not yet wired" in doc, (
        "the docstring must state plainly that the extraction island is "
        "not wired"
    )
    assert "privacy" in doc, (
        "the docstring must name why: wiring it is a privacy decision"
    )


def test_learn_from_turn_docstring_marks_it_unreachable():
    tree = ast.parse(ISLAND_FILE.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "learn_from_turn"
    )
    doc = (ast.get_docstring(fn) or "").lower()
    assert "unreachable" in doc, (
        "learn_from_turn must carry a note that it is unreachable from "
        "the product"
    )
    assert "opt-in" in doc, (
        "it must record that wiring requires an explicit opt-in mode"
    )