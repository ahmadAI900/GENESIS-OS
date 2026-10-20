"""Item 22B (C23): a bare launch target never reaches shutil.which.

ApplicationManager.resolve_application, section 5 (DISCOVERY LAUNCH
TARGET), ran:

    if os.path.isabs(launch_target):
        if os.path.isfile(launch_target):
            return launch_target

        located = shutil.which(launch_target)   # <- NESTED
        if located:
            return located

shutil.which was nested INSIDE the isabs branch, so a BARE launch
target -- "chrome.exe", "chrome", any relative name an application
record legitimately carries -- never reached which() and fell
through the whole resolution chain unresolved (the aliases table
does not know it, and section 7 only retries the raw QUERY when it
ends in ".exe"). Sections 2 (executables) and 4 (single
executable) already ran which() at the right level; only this
section was nested.

REPRODUCED, not assumed, against the committed original (record
whose launch_target is a bare name that IS on PATH -- the same
shape as the real chrome.exe record on a machine where chrome.exe
is on PATH):

    resolve_application("zzqfakeapp")
    -> None        <- launch_target "zzqfakeapp.exe" is on PATH,
                      but which() was never consulted

THE FIX runs shutil.which for non-absolute names too, after the
unchanged absolute-path check. Absolute behaviour is untouched:
an existing absolute path still returns immediately; an absolute
path that does not exist still falls through to which()/the rest.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

from genesis_os.applications.app_manager import ApplicationManager
from genesis_os.applications.application_resolution import (
    ResolutionDecision,
)

MODULE = pathlib.Path("genesis_os") / "applications" / "app_manager.py"

# Distinctive enough that the fuzzy-alias pass cannot match it
# (aliases are empty in these tests anyway).
APP = "zzqfakeapp"


class _StubResult:
    def __init__(self, record):
        self.decision = ResolutionDecision.RESOLVED
        self.application = record


class _StubEngine:
    def __init__(self, record):
        self._record = record

    def resolve(self, query):
        return _StubResult(self._record)


def _manager(tmp_path, monkeypatch, record):
    """ApplicationManager without the heavy discovery construction.

    Only the attributes resolve_application reads are set: the
    (stubbed) resolution engine and EMPTY alias/path tables, so no
    fuzzy alias can accidentally resolve the query.
    """
    (tmp_path / f"{APP}.exe").write_bytes(b"MZ")

    mgr = ApplicationManager.__new__(ApplicationManager)
    mgr.resolution_engine = _StubEngine(record)
    mgr.application_aliases = {}
    mgr.application_paths = {}

    # which() must see ONLY the controlled directory.
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(
        "PATHEXT", ".COM;.EXE;.BAT;.CMD",
    )
    return mgr


# --------------------------------------------------------------------------
# The regression: a bare launch target that IS on PATH must resolve
# --------------------------------------------------------------------------

def test_a_bare_exe_launch_target_resolves_via_which(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch, {
        "executables": [], "paths": [], "executable": None,
        "launch_target": f"{APP}.exe",
    })

    resolved = mgr.resolve_application("fake query")

    assert resolved is not None, (
        "a bare 'chrome.exe'-style launch target that is on PATH "
        "resolved to nothing: shutil.which is nested inside the "
        "isabs branch, so a non-absolute launch target never "
        "reaches it and the whole chain falls through unresolved"
    )
    assert resolved.lower().endswith(f"{APP}.exe"), resolved


def test_a_bare_name_without_extension_resolves_via_which(
    tmp_path, monkeypatch,
):
    mgr = _manager(tmp_path, monkeypatch, {
        "executables": [], "paths": [], "executable": None,
        "launch_target": APP,  # bare name, no .exe; PATHEXT applies
    })

    resolved = mgr.resolve_application("fake query")

    assert resolved is not None, (
        "a bare name launch target that resolves through PATHEXT "
        "on PATH was never consulted -- which() only ran for "
        "absolute names"
    )
    assert resolved.lower().endswith(f"{APP}.exe"), resolved


# --------------------------------------------------------------------------
# The absolute-path behaviour is unchanged
# --------------------------------------------------------------------------

def test_an_existing_absolute_launch_target_still_returns_it(
    tmp_path, monkeypatch,
):
    absolute = tmp_path / f"{APP}.exe"
    mgr = _manager(tmp_path, monkeypatch, {
        "executables": [], "paths": [], "executable": None,
        "launch_target": str(absolute),
    })

    resolved = mgr.resolve_application("fake query")

    assert resolved == str(absolute), (
        f"absolute launch target handling changed: {resolved!r}"
    )


def test_a_missing_absolute_launch_target_still_falls_through(
    tmp_path, monkeypatch,
):
    missing = tmp_path / "definitely_not_installed_zzq.exe"
    mgr = _manager(tmp_path, monkeypatch, {
        "executables": [], "paths": [], "executable": None,
        "launch_target": str(missing),
    })

    resolved = mgr.resolve_application("fake query")

    assert resolved is None, (
        f"a missing absolute target must not resolve: {resolved!r}"
    )


# --------------------------------------------------------------------------
# Structural: which() must not live inside the isabs branch
# --------------------------------------------------------------------------

def test_which_is_not_nested_inside_the_isabs_branch():
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "resolve_application"
    )

    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if "isabs" not in ast.unparse(node.test):
            continue
        body_src = "\n".join(
            ast.unparse(stmt) for stmt in node.body
        )
        if "shutil.which" in body_src:
            offenders.append(ast.unparse(node.test))

    assert not offenders, (
        f"shutil.which is nested inside an isabs branch again: "
        f"{offenders}. A non-absolute launch target would skip "
        "PATH resolution entirely"
    )
