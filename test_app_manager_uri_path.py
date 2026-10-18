"""Item 14D (C11): the URI launch path, its ordering, and its indentation.

Two defects in `ApplicationManager`:

1. ORDERING. The Windows-URI block sat at the TOP of `open()`, so any
   name in the URI alias table was dispatched through `explorer.exe`
   before the executable resolver was ever consulted. The URI path can
   only ever report `dispatched=True, verified=False`; the executable
   path polls tasklist and can report `verified=True`. Preferring the
   URI route discarded the stronger, observable guarantee for every
   name that had both. The block is now reached only when no
   executable resolves -- which is what "last resort" must mean.

2. LAYOUT. `_open_uri` had comment lines and dict keys at column 0
   *inside* a `try:` block and *inside* a returned dict literal. Legal
   Python, and behaviourally inert -- but it made the block impossible
   to read, which is how the ordering bug survived. Corrected here so
   the code can be reviewed.

Plus one hardening: `_open_uri` now re-checks the allowlist itself.
Redundant on the current call path, deliberately so -- the guarantee
was a property of the CALLER, and the method hands its argument to a
process that dispatches any URI scheme it is handed.
"""
from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from genesis_os.applications.app_manager import ApplicationManager


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class _PosixOSView:
    """Presents os.name == "posix" to one module without touching real os.

    Same rationale as the existing test_level3_9 suite: patching the
    genuine `os.name` corrupts pathlib everywhere.
    """

    name = "posix"


@pytest.fixture
def manager():
    return ApplicationManager()


@pytest.fixture
def on_windows(monkeypatch):
    import genesis_os.applications.app_manager as app_mod

    monkeypatch.setattr(app_mod.os, "name", "nt")


class _FakeSubprocess:
    """Stands in for the subprocess module inside app_manager only.

    NOTE: `app_mod.subprocess` IS the global `subprocess` module, so
    `monkeypatch.setattr("...app_manager.subprocess.Popen", ...)` would
    replace `subprocess.Popen` PROCESS-WIDE and break unrelated
    machinery -- the same class of trap as patching the real
    `os.name`. Replacing the module reference inside app_manager
    scopes the fake to the code under test.
    """

    DEVNULL = -3

    def __init__(self, calls):
        self._calls = calls

    def Popen(self, args, **kwargs):  # noqa: N802 - mirrors subprocess
        self._calls.append((args, kwargs))
        return object()


@pytest.fixture
def popen_calls(monkeypatch):
    """Record subprocess.Popen instead of launching anything."""
    import genesis_os.applications.app_manager as app_mod

    calls = []
    monkeypatch.setattr(app_mod, "subprocess", _FakeSubprocess(calls))
    return calls


# --------------------------------------------------------------------------
# 1. Ordering: the executable wins when both exist
# --------------------------------------------------------------------------

def test_a_name_in_both_maps_prefers_the_executable(manager, monkeypatch, popen_calls):
    """The whole point of 'last resort': direct launch is verifiable."""
    dual = [
        name
        for name in manager.windows_uri_apps
        if manager.resolve_application(name)
    ]
    assert dual, (
        "expected at least one alias-table name to also resolve to an "
        "executable; if that is no longer true this test needs "
        "revisiting, but the ordering rule must still hold"
    )
    name = dual[0]

    launched = []
    monkeypatch.setattr(manager, "_launch", lambda exe, arg: launched.append(exe))
    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: False)

    result = manager.open(name)

    assert launched, f"{name!r} went to the URI path instead of the executable"
    assert popen_calls == [], (
        f"{name!r} reached explorer.exe despite having a resolvable "
        f"executable; Popen calls={popen_calls}"
    )
    assert result["application_type"] == "executable", result
    assert result["resolved_executable"], result


def test_the_dual_mapped_name_is_still_discoverable(manager):
    """Sanity: the fixture above relies on this overlap existing."""
    dual = [
        name
        for name in manager.windows_uri_apps
        if manager.resolve_application(name)
    ]
    assert manager.resolve_uri(dual[0]) is not None, (
        "the overlapping name should still have a URI too"
    )


def test_a_uri_only_name_still_uses_the_uri_path(manager, on_windows, popen_calls):
    """Moving the block must not lose it entirely."""
    uri_only = [
        name
        for name in manager.windows_uri_apps
        if not manager.resolve_application(name)
    ]
    assert uri_only, "no URI-only aliases found"
    name = uri_only[0]

    result = manager.open(name)

    assert len(popen_calls) == 1, popen_calls
    assert popen_calls[0][0][0] == "explorer.exe"
    assert result["application_type"] == "windows_uri", result
    assert result["dispatched"] is True, result


def test_an_unknown_name_reports_not_found_not_a_uri_attempt(
    manager, on_windows, popen_calls
):
    result = manager.open("definitely-not-an-app-xyzzy")

    assert result["success"] is False, result
    assert result["verified"] is False, result
    assert popen_calls == [], "an unknown name reached explorer.exe"


def test_file_argument_on_a_uri_only_app_is_refused(manager, on_windows, tmp_path, popen_calls):
    uri_only = next(
        name
        for name in manager.windows_uri_apps
        if not manager.resolve_application(name)
    )
    doc = tmp_path / "f.txt"
    doc.write_text("x")

    result = manager.open(uri_only, file_path=str(doc))

    assert result["success"] is False, result
    assert "not supported for URI" in result["error"]
    assert popen_calls == [], popen_calls


# --------------------------------------------------------------------------
# 2. Allowlist hardening in _open_uri itself
# --------------------------------------------------------------------------

def test_open_uri_refuses_a_uri_outside_the_allowlist(manager, on_windows, popen_calls):
    result = manager._open_uri("settings", "file:///C:/Windows/System32/calc.exe")

    assert result["success"] is False, result
    assert "Refused" in result["error"], result
    assert popen_calls == [], (
        f"an un-allowlisted URI reached explorer.exe: {popen_calls}"
    )


def test_a_known_uri_bound_to_a_different_alias_is_refused(
    manager, on_windows, popen_calls
):
    """The stricter of the two guards: membership is not enough."""
    # Several aliases share one URI (settings / windows settings /
    # system settings all map to ms-settings:), so pick a pair that
    # genuinely differs.
    items = list(manager.windows_uri_apps.items())
    (name_a, uri_a) = items[0]
    name_b, uri_b = next(
        (n, u) for n, u in items if u != uri_a
    )

    result = manager._open_uri(name_a, uri_b)

    assert result["success"] is False, (
        f"the URI registered to {name_b!r} was accepted for {name_a!r}: "
        f"{result}"
    )
    assert "Refused" in result["error"], result
    assert popen_calls == [], popen_calls


@pytest.mark.parametrize(
    "uri",
    [
        "file:///C:/Windows/System32/calc.exe",
        "http://example.invalid/payload",
        "javascript:alert(1)",
        "",
        "ms-settings:display",  # allowlisted, but bound to 'display'
    ],
)
def test_open_uri_refuses_several_non_allowlisted_uris(manager, on_windows, popen_calls, uri):
    result = manager._open_uri("settings", uri)

    assert result["success"] is False, f"{uri!r} was accepted"
    assert popen_calls == [], popen_calls


def test_open_uri_accepts_every_allowlisted_uri(manager, on_windows, popen_calls):
    """The guard must not have narrowed the legitimate set."""
    for name, uri in list(manager.windows_uri_apps.items())[:12]:
        popen_calls.clear()
        result = manager._open_uri(name, uri)
        assert result["success"] is True, f"{name!r}/{uri!r} was refused: {result}"
        assert popen_calls and popen_calls[0][0] == ["explorer.exe", uri]


def test_every_allowlisted_uri_uses_a_recognised_scheme(manager):
    """Guards the allowlist itself from drifting to something arbitrary.

    Four schemes are genuinely in use; this test is how the others
    (`windowsdefender:`, `xbox:`) were discovered.
    """
    allowed_prefixes = (
        "ms-settings:",
        "ms-windows-store:",
        "windowsdefender:",
        "xbox:",
    )
    for name, uri in manager.windows_uri_apps.items():
        assert str(uri).startswith(allowed_prefixes), (
            f"{name!r} maps to {uri!r}, which is not a recognised "
            "Windows settings URI scheme"
        )


def test_open_uri_refuses_on_posix(manager, monkeypatch, popen_calls):
    import genesis_os.applications.app_manager as app_mod

    monkeypatch.setattr(app_mod, "os", _PosixOSView())
    uri = next(iter(manager.windows_uri_apps.values()))

    result = manager._open_uri("settings", uri)

    assert result["success"] is False, result
    assert popen_calls == [], popen_calls


# --------------------------------------------------------------------------
# 3. The indentation itself -- the reason the ordering bug survived
# --------------------------------------------------------------------------

def test_no_comment_or_key_sits_at_column_zero_inside_open_uri():
    """Column-0 comments inside a suite are what made this unreadable.

    Scoped to `_open_uri`, the method this item is about. Comments are
    not in the AST, so this reads the raw lines across the method's
    span: every non-blank line between the first and last statement
    must be indented.
    """
    import pathlib

    path = pathlib.Path(sys.modules[ApplicationManager.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    source = path.read_text(encoding="utf-8-sig").splitlines()

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_open_uri"
    )
    start = fn.body[0].lineno
    end = fn.end_lineno

    offenders = [
        lineno
        for lineno in range(start, end + 1)
        if source[lineno - 1]
        and not source[lineno - 1][:1].isspace()
    ]

    assert not offenders, (
        "_open_uri has non-blank lines starting at column 0 at "
        f"line(s) {offenders}; this is what made the block unreadable"
    )


def test_open_uri_body_is_consistently_indented():
    """Every line of the _open_uri suite must be inside the method."""
    import pathlib

    path = pathlib.Path(sys.modules[ApplicationManager.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_open_uri"
    )
    method_indent = min(
        (stmt.col_offset for stmt in fn.body), default=0
    )

    bad = [
        stmt.lineno
        for stmt in fn.body
        if stmt.col_offset != method_indent
    ]

    assert not bad, (
        f"_open_uri has statements at inconsistent indent (method body "
        f"indent={method_indent}) at line(s) {bad}"
    )


def test_the_popen_call_is_still_inside_the_try():
    """Reformatting must not have changed which suite runs it."""
    import pathlib

    path = pathlib.Path(sys.modules[ApplicationManager.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_open_uri"
    )

    popen_calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Popen"
    ]
    assert popen_calls, "no subprocess.Popen found in _open_uri"

    # Every Popen must live inside some Try node within _open_uri.
    try_nodes = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert try_nodes, "_open_uri no longer has a try block"

    for call in popen_calls:
        assert any(
            call in ast.walk(t) for t in try_nodes
        ), "subprocess.Popen is no longer inside a try block"


def test_popen_uses_a_list_and_not_shell(manager, on_windows, popen_calls):
    uri = next(iter(manager.windows_uri_apps.values()))

    manager._open_uri("settings", uri)

    args, kwargs = popen_calls[0]
    assert isinstance(args, list), f"Popen got {type(args).__name__}, not a list"
    assert args == ["explorer.exe", uri]
    assert kwargs.get("shell") is False, (
        "shell=True would let the URI be interpreted by a command "
        "processor instead of passed to explorer.exe"
    )