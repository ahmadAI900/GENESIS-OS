"""Tiering rules: what makes a test `live` rather than `runtime`.

Committed and reviewable on purpose. Continuation A2 classified tests by
running a blocking probe whose false-positive rate was never measured;
the doc it produced had to retract the conclusions. A rule set that
lives in a file can be read, argued with, and changed.

Every rule here traces to recorded evidence in
``docs/fast_gate_evidence.json`` or to the static scan in
``docs/fast_gate_static_scan.json``. Nothing is assumed harmless because
it looks harmless.

THE ALLOWLIST IS A CLOSED SET
-----------------------------
``HARMLESS_EXECUTABLES`` lists every executable observed in evidence that
does not open a window, open a browser, or touch the network. Anything
NOT on it is treated as not harmless -- including executables nobody has
seen yet, and including ones added later without re-deriving evidence.

Derived from the recorded runs, not chosen by hand:

    cmd.exe /c powershell ...   registry and installed-app queries,
                                read-only, returned as JSON
    tasklist /FI "..."          process enumeration, read-only
    ver                         OS version string, read-only
    node.exe .../cli.js         playwright driver process

NOT on the list, and why:

    notepad.exe        opens a real window
    explorer.exe       opens a real window
    chrome / msedge    a browser
    powershell.exe     only allowlisted when invoked as the read-only
                       query above; a bare powershell.exe can do anything
"""

from __future__ import annotations

# Seconds. A test slower than this is not a fast-gate test, whatever it
# did. Derived from the measured distribution: the live tier's median
# was under a second and its slow tail ran past 60s, so 10s separates
# "did a real thing" from "was merely slow about it".
DURATION_LIMIT_SECONDS = 10.0

# Non-loopback DNS or connect. Loopback is excluded because a test
# talking to its own fixture server has not touched the network.
FORBIDDEN_NETWORK = "non-loopback network"

FORBIDDEN_EVENT_KINDS = {
    "gui": "GUI library call (win32gui/win32api/pyautogui)",
    "browser": "browser or driver launch (selenium/playwright)",
    "os_launch": "OS launch (os.startfile / ShellExecuteW)",
}

# ctypes calls that are pure resource queries against the window
# station. Enumerating windows is a GUI observation, not a harmless read
# of a file, so it is treated as a GUI event. Listed by symbol so a
# narrower decision stays reviewable.
CTYPES_GUI_SYMBOLS = {
    "EnumWindows", "EnumChildWindows", "EnumDesktopWindows",
    "GetForegroundWindow", "SetForegroundWindow",
    "GetWindowTextW", "GetWindowTextLengthW", "GetWindowTextA",
    "GetClassNameW", "GetWindowRect", "GetWindowThreadProcessId",
    "IsWindowVisible", "IsIconic", "IsZoomed",
    "SetWindowPos", "MoveWindow", "ShowWindow", "SetWindowText",
    "SendMessageW", "PostMessageW", "SendMessageA", "PostMessageA",
    "SetCursorPos", "GetCursorPos", "mouse_event", "keybd_event",
    "VkKeyScanA", "VkKeyScanW", "SetProcessDPIAware",
}

# Read-only shell probes, keyed by a distinctive substring of the
# command. Each entry states what it proves it does, because "it looked
# harmless" is not a justification.
HARMLESS_EXECUTABLES = {
    "cmd.exe": (
        "Shell that carries the read-only PowerShell queries below. "
        "Allowlisted only because every observed use was one of those."
    ),
    "tasklist": (
        "Process enumeration. Observed as "
        "`tasklist /FI \"IMAGENAME eq chrome.exe\"`, read-only."
    ),
    "ver": "OS version string. Read-only.",
}

# PowerShell command bodies that are read-only queries. Matched as a
# substring of the recorded command line.
HARMLESS_POWERSHELL_COMMANDS = {
    "Get-AppxPackage": "reads the installed-app package database",
    "Get-StartApps": "reads the Start Apps registry database",
    "Get-CimInstance": "reads WMI inventory",
    "Get-ItemProperty": "reads a registry value",
    "Get-ChildItem": "lists a directory",
    "Test-Path": "checks whether a path exists",
    "Get-Process": "reads the process table",
}

# Executables that are never harmless, listed explicitly so the
# allowlist's closed-set behaviour is auditable at a glance rather than
# inferred from what is missing.
KNOWN_NOT_HARMLESS = {
    "notepad.exe": "opens a real window",
    "explorer.exe": "opens a real window",
    "chrome.exe": "a browser",
    "msedge.exe": "a browser",
    "firefox.exe": "a browser",
    "node.exe": "the playwright driver; it exists only to serve a browser",
}

DURATION_REASON = f"duration over {DURATION_LIMIT_SECONDS}s"
STATIC_REASON = "unexplained static signal"

# The recorder's own tests assert ON the recorder. They import
# subprocess and the GUI libraries by design, and one of them launches a
# deliberately nonexistent executable to prove the error still propagates.
#
# Left to the general rules, every one of them would be marked `live` and
# deselected from `-m "not live" -p record_probe --record` -- the exact
# run in which they are the only thing checking the instrument. That
# would mean the canaries never run in any gate.
#
# So they are exempt by filename, from BOTH the static-signal rule and
# the process-launch rule, and only for the event classes listed here.
# This is deliberately narrow: it covers the two tools/ files, not a
# pattern, and a GUI or browser event still holds them `live`.
RECORDER_SELF_TESTS = ("tools/test_record_probe_canaries.py",
                       "tools/test_record_probe_transparency.py")

# Event kinds exempt for the self-tests above. Anything NOT in this set
# (gui, browser, non-loopback network, a real window launch) still keeps
# a self-test in the live tier.
RECORDER_SELF_TEST_EXEMPT_KINDS = {"process", "dll_load", "ctypes_call"}


def is_recorder_self_test(nodeid: str) -> bool:
    return any(nodeid.startswith(prefix) for prefix in RECORDER_SELF_TESTS)


def static_keys_for(nodeid: str):
    """Index keys that could hold the static signals for one node id.

    The scanner records a method inside a class as `Class::method` and a
    module-level function as `function`, and prefixes both with the file.
    So `a.py::C::m` has to be looked up under all three shapes.

    This lived inline in two places that disagreed -- cross_check.py
    matched on the bare method name while apply_tiering.py matched on a
    file-less `Class::method` -- and each mistake silently produced a
    different, plausible-looking answer. One definition, used by both.
    """
    parts = nodeid.split("::")
    filename = parts[0]
    keys = []
    if len(parts) >= 3:
        keys.append(f"{filename}::" + "::".join(parts[-2:]))
    if len(parts) >= 2:
        keys.append(f"{filename}::{parts[-1]}")
    return keys


# The interpreter running the tests, by absolute path.
#
# Narrow on purpose: `sys.executable` and nothing else. A test that
# spawns the interpreter it is itself running is building test
# infrastructure -- a child pytest for a mutation check, a probe for a
# boundary test -- and introduces no external capability the fast gate
# must avoid. Allowing the BARE name "python.exe" would be different and
# much weaker: a test could ship its own script and gain arbitrary
# execution while looking allowlisted.
#
# Needed by tools/test_require_passed.py and tools/test_tripwire_mutation.py,
# which verify the harness by running it in a child process.

def interpreter_is_harmless(exe: str) -> bool:
    import sys as _sys
    try:
        recorded = str(exe or "").strip().strip('"')
        target = recorded.split()[0] if recorded.split() else ""
        if not target:
            return False
        import os as _os
        same = _os.path.normcase(_os.path.abspath(target)) == \
            _os.path.normcase(_os.path.abspath(_sys.executable))
        return same
    except Exception:
        return False


def is_harmless_executable(exe: str, argv=None) -> tuple:
    """(is_harmless, reason). Closed set: absence from the allowlist means no."""
    name = str(exe or "").strip()
    # A recorded exe can be a whole command line, not just a token.
    token = name.split()[0] if name.split() else ""
    bare = token.split("\\")[-1].split("/")[-1].lower()

    if not bare:
        return False, "empty executable"
    if interpreter_is_harmless(name):
        return True, ("the interpreter running this test session, spawned "
                      "by absolute path as test infrastructure")
    if bare in KNOWN_NOT_HARMLESS:
        return False, KNOWN_NOT_HARMLESS[bare]

    if bare == "powershell.exe" or bare == "pwsh.exe":
        command = " ".join(str(a) for a in (argv or []))
        for needle, what in HARMLESS_POWERSHELL_COMMANDS.items():
            if needle in command:
                return True, f"read-only powershell query: {what}"
        return False, "powershell.exe with a command outside the read-only set"

    for allowed, why in HARMLESS_EXECUTABLES.items():
        if bare == allowed.lower():
            return True, f"{bare} is allowlisted: {why}"
    return False, f"{bare} is not on the harmless allowlist"


def event_reasons(events, exempt_kinds=()) -> list:
    """Human-readable reasons an event list blocks the runtime tier."""
    reasons = []
    for event in events:
        kind = event.get("kind")
        count = event.get("count", 1)
        api = event.get("api", "")

        if kind in exempt_kinds:
            continue
        if kind in FORBIDDEN_EVENT_KINDS:
            reasons.append(f"{FORBIDDEN_EVENT_KINDS[kind]}: {api} x{count}")
        elif kind == "network":
            if not event.get("loopback", False):
                reasons.append(
                    f"{FORBIDDEN_NETWORK}: {event.get('host', '?')} x{count}")
        elif kind == "ctypes_call":
            symbol = api.split(".")[-1]
            if symbol in CTYPES_GUI_SYMBOLS:
                reasons.append(f"GUI window-station call: {api} x{count}")
        elif kind == "process":
            ok, why = is_harmless_executable(event.get("exe", ""),
                                             event.get("argv"))
            if not ok:
                reasons.append(f"process launch ({why}): "
                               f"{event.get('exe', '?')[:80]}")
    return reasons


def classify(events, seconds, static_signals, explained_signals=(),
             exempt_kinds=()):
    """Return (tier, [reasons]). `runtime` requires positive evidence."""
    reasons = event_reasons(events, exempt_kinds=exempt_kinds)

    if seconds is not None and seconds > DURATION_LIMIT_SECONDS:
        reasons.append(f"{DURATION_REASON} ({seconds:.2f}s)")

    unexplained = sorted(set(static_signals) - set(explained_signals))
    for signal in unexplained:
        reasons.append(f"{STATIC_REASON}: {signal}")

    if reasons:
        return "live", reasons
    return "runtime", []