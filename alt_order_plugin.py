"""Alternate collection ordering for F5 regression runs.

Orders collected items as:
  1. test files touched by the F5 workspace-boundary work, first
  2. `test_phase3_trigger_hardening` before `test_phase3_control_plane_maturity`
  3. everything else in reverse-alphabetical module order

The point is to break the default ordering that the suite has been
green under, so that state leaking between tests would show up rather
than hiding behind a lucky sequence.
"""
import pytest

TOUCHED = {
    "test_workspace_boundary.py",
    "test_blast_radius.py",
    "test_phase2_agent_framework_adapter_expansion.py",
    "test_level3_3_browser_select_download_upload.py",
    "test_level3_4_document_edit_transform_verify.py",
    "test_level3_9_natural_language_execution.py",
    "test_level3_3_execution_maturity.py",
    "test_unified_executor.py",
}

# Must precede control_plane regardless of alphabetical order.
PRIORITY = {
    "test_phase3_trigger_hardening.py": 0,
    "test_phase3_control_plane_maturity.py": 1,
}


def _module(item):
    return item.nodeid.split("::")[0].replace("\\", "/")


def _sort_key(item):
    mod = _module(item)
    base = mod.rsplit("/", 1)[-1]
    touched = 0 if base in TOUCHED else 1
    if base in PRIORITY:
        return (touched, 0, PRIORITY[base], mod, item.nodeid)
    # reverse-alphabetical on the module name
    return (touched, 1, 0, _rev(base), item.nodeid)


def _rev(text):
    """Sort key giving reverse-alphabetical order for `text`."""
    return tuple(-ord(ch) for ch in text)


def pytest_collection_modifyitems(session, config, items):
    items.sort(key=_sort_key)