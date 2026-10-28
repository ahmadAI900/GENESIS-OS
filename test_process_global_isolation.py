"""Ordered proof that process-global state is restored between tests.

The previous leak proof lived in ``test_phase0_mixed_data_flow.py``,
which is marked ``live``. The fast gate deselects the whole module, so
ordering 2 never ran it and the two tests were vacuous: each one set a
value and then asserted the same value in the same test.

This module is deliberately non-live. Test A leaks a ``GENESIS_*`` key
and the process cwd. Test B runs afterwards and asserts both are gone.
If the autouse isolation fixture below is removed, test B fails.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

_CWD_BEFORE_LEAK_TEST: Path | None = None


@pytest.fixture(autouse=True)
def _restore_process_globals():
    """Save and restore GENESIS_* keys and the process cwd around a test."""
    genesis_before = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("GENESIS_")
    }
    cwd_before = Path.cwd()
    yield
    genesis_after = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("GENESIS_")
    }
    for key in set(genesis_after) - set(genesis_before):
        del os.environ[key]
    os.environ.update(genesis_before)
    try:
        if Path.cwd() != cwd_before:
            os.chdir(cwd_before)
    except OSError:
        pass


def test_a_a_test_that_leaks_global_state(tmp_path):
    """Leak a GENESIS_* key and change cwd; the fixture must undo both."""
    global _CWD_BEFORE_LEAK_TEST
    _CWD_BEFORE_LEAK_TEST = Path.cwd()

    os.environ["GENESIS_LEAK_PROBE_KEY"] = "leaked-value"
    os.chdir(tmp_path)

    assert os.environ["GENESIS_LEAK_PROBE_KEY"] == "leaked-value"
    assert Path.cwd() == tmp_path


def test_b_the_previous_test_leaked_nothing():
    """State set by test A must not be visible here."""
    assert _CWD_BEFORE_LEAK_TEST is not None, (
        "test A did not run first; the ordered proof is broken"
    )
    assert "GENESIS_LEAK_PROBE_KEY" not in os.environ, (
        "GENESIS_LEAK_PROBE_KEY leaked from the previous test: "
        f"{os.environ.get('GENESIS_LEAK_PROBE_KEY')!r}"
    )
    assert Path.cwd() == _CWD_BEFORE_LEAK_TEST, (
        f"cwd leaked from the previous test: {Path.cwd()} != "
        f"{_CWD_BEFORE_LEAK_TEST}"
    )


def test_the_process_global_isolation_fixture_is_still_autouse():
    """AST guard: deleting or de-autousing the fixture fails the gate."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    fixture = next(
        (
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_restore_process_globals"
        ),
        None,
    )
    assert fixture is not None, (
        "the autouse _restore_process_globals fixture was deleted"
    )
    decorators = [ast.unparse(dec) for dec in fixture.decorator_list]
    assert "pytest.fixture(autouse=True)" in decorators, (
        "the process-global isolation fixture is no longer autouse: "
        f"{decorators}"
    )
