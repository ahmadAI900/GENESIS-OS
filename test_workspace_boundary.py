"""Workspace boundary: fail-closed behaviour, key coverage, and platform
edge cases.

The boundary is the component most able to fail OPEN, because a path
value that fails to parse returns "no target", and the caller reads
that as "inside". Most of this file exists to pin that shut.
"""
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent

from genesis_os import workspace_boundary as WB
from genesis_os.blast_radius import resolve_blast_radius
from genesis_os.capabilities import BlastRadius
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.workspace_boundary import (
    WORKSPACE_ROOT_ENV,
    _keys_for_capability,
    arguments_escape_workspace,
    boundary_is_enforced,
    resolve_target_path,
    BoundaryConfigurationError,
    UnresolvablePathError,
    workspace_root,
)

# Names that are or plausibly are filesystem paths. Used by the
# registry-derived coverage test so a NEW capability declaring one of
# these without it being scanned fails CI rather than silently
# shipping an ungated operation.
PATH_LIKE_NAMES = frozenset({
    "path", "paths", "path1", "path2", "file_path", "filepath", "file",
    "filename", "dir", "dir_path", "dest", "destination", "target",
    "source", "src", "output", "output_path", "out_path", "save_path",
    "folder", "folder_path", "directory", "target_path", "input_path",
    "source_path", "from_path", "to_path", "new_path", "old_path",
    "new_name", "download_path", "upload_path", "csv_path", "json_path",
    "template_path", "results_path", "report_path", "output_dir",
    "base_path", "workspace", "location", "archive_path", "extract_to",
    "pattern_path",
})


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """Unique in-workspace root, restored via monkeypatch (item 19)."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(root))
    return root


def _outside(tmp_path):
    other = tmp_path / "other"
    other.mkdir(exist_ok=True)
    return other


# --------------------------------------------------------------------------
# Fail closed on unparseable path-bearing values.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("value", [
    "a\x00b",            # embedded NUL: realpath raises ValueError
    123, 1.5, True,      # wrong types
    ["a", "b"], {}, ("a",), {1, 2},
    "a" * 5000,          # over-long
])
def test_unparseable_path_value_fails_closed(ws, value):
    assert arguments_escape_workspace({"path": value}) is not None


def test_non_string_raises_rather_than_returning_none():
    with pytest.raises(UnresolvablePathError):
        resolve_target_path(123)
    with pytest.raises(UnresolvablePathError):
        resolve_target_path(["a"])


@pytest.mark.parametrize("value", [
    None, "", "   ", "https://host/p", "computer", "screen", "default",
])
def test_genuinely_absent_target_is_not_an_escape(ws, value):
    assert arguments_escape_workspace({"path": value}) is None


@pytest.mark.parametrize("value", [".", ".."])
def test_dot_paths_resolve_and_escape_rather_than_being_treated_as_absent(
    ws, tmp_path, value, monkeypatch
):
    """'.' and '..' are REAL paths pointing above the root.

    They were once in the sentinel set, which read as "no target" and
    therefore INSIDE - a fail-open.
    """
    monkeypatch.chdir(tmp_path)
    assert arguments_escape_workspace({"path": value}) is not None


# --------------------------------------------------------------------------
# Configuration must not silently disarm the boundary.
# --------------------------------------------------------------------------
def test_empty_root_is_enforced_not_disarmed(monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, "   ")
    assert boundary_is_enforced() is True


def test_unresolvable_root_is_enforced_not_disarmed(monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, "Z:\\" + "x" * 6000)
    assert boundary_is_enforced() is True


def test_unset_root_is_the_off_switch(monkeypatch):
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    assert boundary_is_enforced() is False
    assert arguments_escape_workspace({"path": "C:/anywhere/x"}) is None


# ---------------------------------------------------------------------------
# 2026-10-14 (audit D-12): two more ways a configured root used to be
# accepted when it should have been refused. Both failed OPEN.
# ---------------------------------------------------------------------------

def test_relative_root_is_refused_not_resolved_against_cwd(monkeypatch):
    """`Path("x").resolve()` depends on the process CWD.

    The shell that launches Genesis and the test that runs afterwards can
    have different working directories, so the operator configures one
    path and the runtime silently enforces another. Refuse instead.
    """
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, "some_relative_dir")
    with pytest.raises(BoundaryConfigurationError) as caught:
        workspace_root()
    assert "RELATIVE" in str(caught.value)


def test_dot_relative_root_is_refused_too(monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, ".\\workspace")
    with pytest.raises(BoundaryConfigurationError):
        workspace_root()


def test_nonexistent_root_is_refused_by_name(monkeypatch):
    """A nonexistent root makes every path look like an escape.

    The failure mode is then "nothing is inside the workspace", which
    hides the real cause. Name it at configuration time instead.
    """
    missing = str(BACKEND.parent / ".genesis_workspace" / "definitely_absent")
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, missing)
    with pytest.raises(BoundaryConfigurationError) as caught:
        workspace_root()
    assert "does not exist" in str(caught.value)


def test_a_file_is_not_a_usable_root(monkeypatch, tmp_path):
    not_a_dir = tmp_path / "a_file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(not_a_dir))
    with pytest.raises(BoundaryConfigurationError):
        workspace_root()


def test_an_existing_absolute_root_still_works(monkeypatch, tmp_path):
    """The stricter rules must not break the normal case."""
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(root))
    assert workspace_root() == root.resolve()
    assert boundary_is_enforced() is True


def test_refused_roots_still_report_as_enforced(monkeypatch):
    """Failing closed must not be reported as disarmed.

    A caller that catches BoundaryConfigurationError and treats the
    boundary as inactive would undo the whole point of raising.
    """
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, "relative_thing")
    assert boundary_is_enforced() is True


def test_config_is_read_per_call(monkeypatch, tmp_path):
    """No import-time caching in either direction (ledger item 19)."""
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(a))
    assert arguments_escape_workspace({"path": str(b / "x")}) is not None
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(b))
    assert arguments_escape_workspace({"path": str(b / "x")}) is None
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(a))
    assert arguments_escape_workspace({"path": str(b / "x")}) is not None


# --------------------------------------------------------------------------
# Windows path normalisation regressions.
# --------------------------------------------------------------------------
def test_extended_length_prefix_inside_is_inside(ws):
    """\\\\?\\C:\\... must compare equal to its own non-prefixed form."""
    f = ws / "in.txt"
    f.write_text("x")
    assert arguments_escape_workspace({"path": "\\\\?\\" + str(f)}) is None


def test_extended_length_prefix_outside_is_outside(ws, tmp_path):
    o = _outside(tmp_path) / "s.txt"
    assert arguments_escape_workspace({"path": "\\\\?\\" + str(o)}) is not None


@pytest.mark.parametrize("value", [
    "\\\\server\\share\\x.txt",
    "\\\\?\\UNC\\server\\share\\x.txt",
])
def test_unc_is_outside(ws, value):
    """A UNC path is a network location, never inside a local root.

    The \\?\\UNC form previously returned None, which the caller reads
    as INSIDE - the exact fail-open this module exists to prevent.
    """
    assert arguments_escape_workspace({"path": value}) is not None


def test_sibling_directory_with_name_prefix_is_outside(ws, tmp_path):
    """commonpath semantics, not str.startswith."""
    root = ws.parent / (ws.name + "_secret")
    root.mkdir(exist_ok=True)
    assert arguments_escape_workspace({"path": str(root / "x")}) is not None


# --------------------------------------------------------------------------
# Registry-derived key coverage (fails CI on a future gap).
# --------------------------------------------------------------------------
def test_every_registry_path_like_input_is_scanned():
    """NEW capability with an unscanned path-like input must fail CI.

    A name is acceptable if it is scanned for that capability, OR if
    it appears in _CATEGORY_SCOPED_KEYS, meaning the design has
    consciously scoped it (`target` is a file for document/spreadsheet
    but a UI element for gui, an app name for application.window_list,
    and a settings name for system.open_settings; scanning it
    unconditionally would escalate all GUI automation to Tier 1).

    A genuinely new name such as `dest_path` still fails.
    """
    deliberate = set(WB._CATEGORY_SCOPED_KEYS)
    gaps = []
    for descriptor in CapabilityRegistry.all():
        keys = _keys_for_capability(descriptor.capability_id)
        category = getattr(descriptor.category, "name", str(descriptor.category))
        for raw in descriptor.supported_inputs:
            name = raw if isinstance(raw, str) else getattr(raw, "name", str(raw))
            if name.lower() not in PATH_LIKE_NAMES:
                continue
            if name not in keys and name not in deliberate:
                gaps.append(f"{descriptor.capability_id}.{name} [{category}]")
    assert not gaps, "path-like inputs not scanned by the boundary: " + ", ".join(gaps)


def test_known_gap_inputs_are_covered():
    """Inputs found by the coverage audit are now scanned."""
    for capability_id, key in [
        ("document.compare", "path1"),
        ("document.compare", "path2"),
        ("spreadsheet.compare", "path1"),
        ("spreadsheet.compare", "path2"),
        ("file.rename", "new_name"),
        ("folder.rename", "new_name"),
        ("filesystem.search", "location"),
        ("document.create", "target"),
        ("spreadsheet.add_column", "target"),
    ]:
        assert key in _keys_for_capability(capability_id), (
            f"{capability_id}.{key} is not scanned"
        )


# --------------------------------------------------------------------------
# `target` is overloaded: a file for document/spreadsheet, a UI element
# for gui, an app name for application.window_list, a settings name for
# system.open_settings. Scanning it unconditionally would escalate all
# GUI automation.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("capability_id,arguments", [
    ("gui.double_click", {"target": "OK button"}),
    ("gui.drag", {"target": "Save As"}),
    ("gui.hotkey", {"target": "notepad"}),
    ("application.window_list", {"target": "Calculator"}),
    ("system.open_settings", {"target": "Bluetooth"}),
])
def test_non_path_target_values_stay_inside(ws, capability_id, arguments):
    assert arguments_escape_workspace(arguments, capability_id=capability_id) is None


def test_gui_target_does_not_escalate_blast_radius(ws):
    tier = resolve_blast_radius("gui.double_click", {"target": "OK button"})
    assert tier is BlastRadius.REVERSIBLE_LOCAL


def test_gui_target_is_not_treated_as_a_relative_path(ws, monkeypatch, tmp_path):
    """A UI element name is not a path under cwd."""
    monkeypatch.chdir(ws)
    assert arguments_escape_workspace(
        {"target": "OK button"}, capability_id="gui.double_click"
    ) is None


def test_document_target_outside_escalates(ws, tmp_path):
    o = _outside(tmp_path) / "r.pdf"
    assert arguments_escape_workspace(
        {"target": str(o)}, capability_id="document.create"
    ) is not None
    assert resolve_blast_radius("document.create", {"target": str(o)}) is (
        BlastRadius.IRREVERSIBLE_OR_OUTWARD
    )


def test_compare_with_outside_second_path_escalates(ws, tmp_path):
    """path1/path2 were unscanned, so this compare was never gated."""
    o = _outside(tmp_path) / "b.pdf"
    args = {"path1": str(ws / "a.pdf"), "path2": str(o)}
    assert arguments_escape_workspace(args, capability_id="document.compare") is not None
    assert resolve_blast_radius("document.compare", args) is (
        BlastRadius.IRREVERSIBLE_OR_OUTWARD
    )


def test_compare_with_both_paths_inside_stays_reversible(ws):
    args = {"path1": str(ws / "a.pdf"), "path2": str(ws / "b.pdf")}
    assert arguments_escape_workspace(args, capability_id="document.compare") is None
    assert resolve_blast_radius("document.compare", args) is (
        BlastRadius.REVERSIBLE_LOCAL
    )


def test_key_set_resolution_never_raises(ws):
    """_keys_for_capability must not raise.

    blast_radius fails CLOSED on any exception from the boundary check,
    so a bug here silently escalates every reversible capability to
    Tier 1. That regression happened once (tuple | set) and would have
    gated the entire product.
    """
    for descriptor in CapabilityRegistry.all():
        keys = _keys_for_capability(descriptor.capability_id)
        assert isinstance(keys, frozenset), descriptor.capability_id
        assert "path" in keys, descriptor.capability_id


def test_unknown_capability_id_falls_back_to_base_keys():
    keys = _keys_for_capability("does.not.exist")
    assert "path" in keys and isinstance(keys, frozenset)
    assert _keys_for_capability(None) == frozenset(WB._PATH_KEYS)


def test_traversal_is_escaped(ws, tmp_path):
    assert arguments_escape_workspace({"path": str(ws / ".." / "x")}) is not None


def test_no_path_arguments_never_escape(ws):
    assert arguments_escape_workspace({"query": "hello"}) is None
    assert arguments_escape_workspace({}) is None
    assert arguments_escape_workspace() is None
    assert arguments_escape_workspace("not-a-mapping") is None