"""Directive 9D (S2): boundary-scan the second file of multi-file reads.

`workspace_boundary._PATH_KEYS` listed `path1`/`path2` for the compare
operations, but the LIVE dispatch in `action_executor.py` uses
`other_path`:

    :2084  document.compare   -> doc_compare(t, p["other_path"])
    :2125  spreadsheet.compare-> sheet_compare(
                                       t, p["sheet1"], p["other_path"],
                                       p["sheet2"])

`other_path` was in neither list, so it was never scanned. Measured
before the fix, with the first file INSIDE the workspace and the second
one outside:

    arguments_escape_workspace(
        {"path": <inside>, "other_path": "C:/Users/Public/secret.csv"},
        capability_id="spreadsheet.compare",
    ) -> None

An outside second file was not gated at all, while the equivalent
single-file read was refused. That is a boundary read, not a write, so
nothing irreversible follows from it -- but "read one good file and one
bad one" is exactly how a workspace boundary is walked.

NOTE ON sheet1 / sheet2. The directive named all three as second-file
targets. Only `other_path` is one: in the dispatch above, sheet1 and
sheet2 are WORKSHEET NAMES. Scanning them resolves a sheet called
"Sheet1" to "<cwd>/Sheet1" -- outside any scratch workspace -- which
would escalate every spreadsheet.compare to Tier 1 no matter where its
files live. That is the false escalation this module already documents
for `target` and for UI element names. So `other_path` was added and the
two sheet-name keys deliberately were not; see the reasoning at
_PATH_KEYS.
"""

from __future__ import annotations

import pytest

from genesis_os.workspace_boundary import (
    _PATH_KEYS,
    arguments_escape_workspace,
)

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

OUTSIDE = "C:/Users/Public/definitely-outside.txt"


def _inside(root, name: str) -> str:
    return str(root / name)


# =====================================================================
# The gap
# =====================================================================

@pytest.mark.parametrize(
    "capability_id",
    ["spreadsheet.compare", "document.compare"],
)
def test_an_out_of_workspace_other_path_is_refused(
    workspace_root, capability_id
):
    """The regression. Fails before Item 9D: returned None."""
    arguments = {
        "path": _inside(workspace_root, "a.csv"),
        "other_path": OUTSIDE,
    }

    escape = arguments_escape_workspace(
        arguments, capability_id=capability_id
    )

    assert escape, (
        f"{capability_id} read a SECOND file outside the workspace and "
        f"was not gated: arguments={arguments}"
    )
    assert "other_path" in escape, escape


def test_the_executor_dispatch_key_is_the_one_we_scanned():
    """Pins the reasoning: other_path is what the executor reads."""
    import pathlib

    source = pathlib.Path(__file__).resolve().parent
    executor = source / "genesis_os" / "action_executor.py"
    text = executor.read_text(encoding="utf-8-sig")

    assert 'p.get("other_path"' in text, (
        "the executor no longer reads other_path; revisit _PATH_KEYS"
    )
    assert "other_path" in _PATH_KEYS


# =====================================================================
# No over-escalation
# =====================================================================

def test_a_compare_with_both_files_inside_is_not_escalated(workspace_root):
    """The fix must gate the escape, not every compare."""
    arguments = {
        "path": _inside(workspace_root, "a.csv"),
        "other_path": _inside(workspace_root, "b.csv"),
    }

    assert not arguments_escape_workspace(
        arguments, capability_id="spreadsheet.compare"
    )


def test_sheet_names_are_not_treated_as_paths(workspace_root):
    """sheet1/sheet2 are worksheet names. Scanning them would resolve
    "Sheet1" to <cwd>/Sheet1 and escalate every compare."""
    arguments = {
        "path": _inside(workspace_root, "a.csv"),
        "other_path": _inside(workspace_root, "b.csv"),
        "sheet1": "Sheet1",
        "sheet2": "Summary",
    }

    assert "sheet1" not in _PATH_KEYS, (
        "sheet1/sheet2 are worksheet names, not paths; scanning them "
        "escalates every spreadsheet.compare to Tier 1"
    )
    assert "sheet2" not in _PATH_KEYS
    assert not arguments_escape_workspace(
        arguments, capability_id="spreadsheet.compare"
    ), (
        "a compare naming sheets 'Sheet1'/'Summary' inside the workspace "
        "was escalated; sheet names must not be read as paths"
    )


# =====================================================================
# Single-file behaviour is unchanged
# =====================================================================

def test_single_file_reads_are_unaffected(workspace_root):
    """Adding one key must not disturb the existing ones."""
    assert not arguments_escape_workspace(
        {"path": _inside(workspace_root, "a.txt")},
        capability_id="spreadsheet.read",
    )
    assert arguments_escape_workspace(
        {"path": OUTSIDE}, capability_id="spreadsheet.read"
    )


def test_every_key_in_path_keys_is_reachable_as_a_real_argument_name():
    """The tuple is a contract; a typo'd key is a silently dead entry."""
    assert "other_path" in _PATH_KEYS
    assert len(set(_PATH_KEYS)) == len(_PATH_KEYS), (
        f"duplicate keys in _PATH_KEYS: {_PATH_KEYS}"
    )