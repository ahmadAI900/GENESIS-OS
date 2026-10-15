"""Recording probe: observe real capability use without ever blocking it.

REPLACES the blocking probe, which failed its own validation controls in
both directions (Continuation A2):

    broad launcher list  -> positive controls 9/9, negative control FALSE POSITIVE
    narrow launcher list -> positive controls 4/9, negative control FALSE POSITIVE

Blocking was the wrong instrument. The real launch path transits the same
aggregate modules as ordinary test setup, so no module-name list separates
"opened notepad" from "constructed something that touches subprocess on
the way through". And a block raised inside an async task surfaced as a
playwright ``TargetClosedError``, swallowing the cause entirely.

A recorder cannot have that failure mode. It never raises, so nothing is
swallowed, and it observes instead of guessing.

Opt-in only -- never loaded in a normal run:

    PYTHONPATH=tools pytest -m live  -p record_probe --record
    PYTHONPATH=tools pytest          -p record_probe --record

Output file
-----------
``--record-out`` defaults to ``docs/fast_gate_runs/<tag>.json`` where the
tag comes from ``--record-tag``. Continuation A3 merged every run into one
file, so a control run and the real run overwrote each other's evidence;
separation is the default and merging is opt-in via ``--record-merge``.

Three recording layers, and why three
-------------------------------------
1. ``sys.addaudithook`` -- process, OS launch, network. Immune to import
   timing and to stale references: CPython raises the event at the call
   site, not at the module attribute. Audit hooks cannot be removed once
   installed, so the hook is installed once and guarded by ``_ACTIVE``.

2. ``ctypes.CDLL.__getattr__`` -- the OS window calls. This codebase does
   not use ``win32gui`` at all for real window work: ``window_models.py``
   and ``application_state_machine.py`` drive ``ctypes.windll.user32``
   directly. There is no ``ctypes.call_function`` audit event in CPython
   3.12, so wrapping the DLL attribute lookup is the only observation
   point that catches the real product path.

3. ``sys.meta_path`` loader wrapper -- ``win32gui``, ``win32api``,
   ``pyautogui``, ``selenium.webdriver``, ``playwright.sync_api``. These
   are imported lazily by the code under test, so wrapping at install time
   alone wrapped nothing. The wrapper fires when the module *finishes*
   loading; already-loaded modules are wrapped at install.

Known limitation (stale references)
-----------------------------------
A name bound by ``from x import y`` *before* the wrapper is installed keeps
the original object, and no post-hoc wrapping can reach it. Audit events are
immune to this; module-attribute wrappers are not. Measured for this
codebase in ``docs/fast_gate_tiering.md``.
"""

from __future__ import annotations

import importlib.abc
import json
import os
import socket
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND / "tools") not in sys.path:
    sys.path.insert(0, str(BACKEND / "tools"))

EVIDENCE_PATH = BACKEND / "docs" / "fast_gate_evidence.json"

# nodeid -> {"events": [...], "seconds": float}
RECORDS: dict = {}
_CURRENT = {
    "nodeid": None,
    "events": [],
    "index": {},
    "dropped": 0,
    "started": None,
}


def _reset_current():
    _CURRENT["events"] = []
    _CURRENT["index"] = {}
    _CURRENT["dropped"] = 0
    _CURRENT["nodeid"] = None

# Audit hooks cannot be uninstalled, so every hook checks this. It is only
# true between pytest_configure and process exit.
_ACTIVE = False

# Extra capture frames, owned by consumers other than the recorder plugin
# (currently the fast-gate tripwire). See `_record`.
_CAPTURE_STACK: list = []

_INSTALL_STATE = {
    "audit": False,
    "ctypes": False,
    "meta_path": False,
    "wrapped_modules": [],
    "stale_bindings": [],
}

# Loopback is never a "real network" event: a test connecting to
# 127.0.0.1 is talking to its own fixture server.
LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "", "0.0.0.0.0"}

# A single window enumeration raises hundreds of ctypes events, and the
# suite runs thousands of tests. Storing every raw call produced a 262KB
# file for 16 tests and forced a cap, which is the worst of both: huge
# files AND silent data loss.
#
# Instead, events are AGGREGATED: identical (kind, api, target) collapse
# into one entry with a count. Nothing is dropped -- `user32.EnumWindows`
# called 288 times is stored as count=288 -- so the evidence is complete
# and small. The cap below is on DISTINCT entries, and hitting it is
# recorded, never silent.
MAX_DISTINCT_EVENTS_PER_TEST = 150

_AUDIT_WATCH = frozenset((
    "subprocess.Popen",
    "os.system",
    "os.startfile",
    "os.posix_spawn",
    "os.fork",
    "os.exec",
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.sendto",
    "socket.sendmsg",
    "ctypes.dlopen",
    "ctypes.dlsym",
    "ctypes.call_function",
))

# Fields that identify "the same event" for aggregation purposes.
_IDENTITY_FIELDS = ("api", "exe", "path", "host", "symbol", "dll")


def _event_key(kind: str, detail: dict):
    return (kind,) + tuple(detail.get(f, "") for f in _IDENTITY_FIELDS)


def event_key(event: dict):
    """Public: the aggregation identity of a recorded event.

    The tripwire compares event keys across two moments (end of body,
    end of teardown) to spot capabilities reached during teardown, so
    the key definition cannot live behind a private name.
    """
    return _event_key(event.get("kind", ""), event)


def _record(kind: str, detail: dict) -> None:
    """Record into every active capture frame.

    Multiple consumers: the recorder plugin writes evidence files, the
    tripwire fixture decides whether a test may stay in the fast gate.
    Both need the same events, and they clean up at different moments --
    the plugin's ``pytest_runtest_teardown`` runs BEFORE fixture teardown
    (measured, see docs/fast_gate_tiering.md), so whichever consumer
    finished first would otherwise find the buffer already emptied.

    Writing to all frames rather than the newest keeps both correct: a
    frame that is present gets every event, and a consumer that has
    already detached simply stops receiving them.
    """
    if _CURRENT["nodeid"] is not None:
        _add_to_frame(_CURRENT, kind, detail)
    for frame in _CAPTURE_STACK:
        if frame["nodeid"] is not None:
            _add_to_frame(frame, kind, detail)


def _add_to_frame(frame, kind: str, detail: dict) -> None:
    index = frame["index"]
    key = _event_key(kind, detail)
    existing = index.get(key)
    if existing is not None:
        existing["count"] += 1
        return
    events = frame["events"]
    if len(events) >= MAX_DISTINCT_EVENTS_PER_TEST:
        frame["dropped"] += 1
        return
    entry = {"kind": kind, **detail, "count": 1}
    events.append(entry)
    index[key] = entry


def new_capture(nodeid: str) -> dict:
    """A fresh, empty capture frame for an independent consumer."""
    return {"nodeid": nodeid, "events": [], "index": {}, "dropped": 0}


def ensure_installed() -> None:
    """Install the recorders even when ``--record`` was not passed.

    The audit hook cannot be removed once added, so this is idempotent
    and process-wide by nature. Cost when no frame is attached is a
    frozenset membership test per auditable operation.
    """
    _install_recorders()


def is_loopback(host: str) -> bool:
    return str(host).lower() in LOOPBACK


def events_for(nodeid):
    """Test helper: the events recorded for one node id."""
    return RECORDS.get(nodeid, {}).get("events", [])


# ---------------------------------------------------------------------------
# pytest plumbing
# ---------------------------------------------------------------------------
def pytest_addoption(parser):
    group = parser.getgroup("genesis-recorder")
    group.addoption("--record", action="store_true", default=False,
                    help="record real-capability events per test")
    group.addoption("--record-out", default=None,
                    help="exact path for the evidence JSON "
                         "(default: docs/fast_gate_runs/<tag>.json)")
    group.addoption("--record-tag", default="run",
                    help="name for the default evidence file, so a control "
                         "run and the real run never write the same file")
    group.addoption("--record-merge", action="store_true", default=False,
                    help="merge into an existing evidence file instead of "
                         "replacing it (off by default: merging silently "
                         "conflated control and real evidence in A3)")


def pytest_configure(config):
    if not config.getoption("--record", default=False):
        return
    if _INSTALL_STATE["audit"]:
        return
    # NOTE: query by DEST name, not by the dashed flag. pytest looks the
    # name up in `_opt2dest`, which is keyed on the literal flag as it was
    # declared. `getoption("--record_tag")` misses that map, hits
    # AttributeError and silently returns the default -- so every run
    # ignored --record-tag and overwrote the same file. Measured: the
    # first control run wrote docs/fast_gate_runs/run.json despite being
    # given --record-tag control.
    out = config.getoption("record_out", default=None)
    if not out:
        tag = config.getoption("record_tag", default="run") or "run"
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in tag)
        out = str(BACKEND / "docs" / "fast_gate_runs" / f"{safe}.json")
    config._genesis_record_path = out
    config._genesis_record_merge = bool(
        config.getoption("record_merge", default=False))
    _install_recorders()


def pytest_unconfigure(config):
    global _ACTIVE
    _ACTIVE = False


def pytest_runtest_setup(item):
    _CURRENT["nodeid"] = item.nodeid
    _reset_current()
    _CURRENT["nodeid"] = item.nodeid
    _CURRENT["started"] = time.perf_counter()


def pytest_runtest_teardown(item, nextitem):
    started = _CURRENT.pop("started", None)
    seconds = round(time.perf_counter() - started, 4) if started else 0.0
    nodeid = item.nodeid
    events = list(_CURRENT["events"])
    dropped = _CURRENT["dropped"]
    _reset_current()
    prior = RECORDS.get(nodeid, {"events": [], "seconds": 0.0, "dropped": 0})
    merged = _merge_events(prior["events"], events)
    RECORDS[nodeid] = {
        "events": merged,
        "seconds": max(prior.get("seconds", 0.0), seconds),
        "dropped": prior.get("dropped", 0) + dropped,
    }


def _merge_events(existing, incoming):
    """Union of two event lists, summing counts for identical events."""
    out = [dict(e) for e in existing]
    index = {_event_key(e["kind"], e): e for e in out}
    for event in incoming:
        key = _event_key(event["kind"], event)
        match = index.get(key)
        if match is not None:
            match["count"] += event.get("count", 1)
        else:
            copied = dict(event)
            out.append(copied)
            index[key] = copied
    return out


def pytest_sessionfinish(session, exitstatus):
    global _ACTIVE
    _ACTIVE = False
    out = getattr(session.config, "_genesis_record_path", None)
    if not out:
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {}
    if getattr(session.config, "_genesis_record_merge", False) and path.is_file():
        try:
            merged = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            merged = {}
    for nodeid, data in RECORDS.items():
        if nodeid in merged:
            merged[nodeid]["events"] = _merge_events(
                merged[nodeid]["events"], data["events"])
            merged[nodeid]["seconds"] = max(
                merged[nodeid].get("seconds", 0.0), data["seconds"])
            merged[nodeid]["dropped"] = (
                merged[nodeid].get("dropped", 0) + data.get("dropped", 0))
        else:
            merged[nodeid] = data
    merged["__meta__"] = {
        "tag": getattr(session.config.option, "record_tag", None) or "run",
        "tests": len(RECORDS),
        "argv": list(sys.argv),
        "max_distinct_events_per_test": MAX_DISTINCT_EVENTS_PER_TEST,
        "truncated_tests": sorted(
            n for n, d in RECORDS.items() if d.get("dropped")),
        "install": _INSTALL_STATE,
    }
    path.write_text(json.dumps(merged, indent=1, sort_keys=True),
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# Layer 1: audit hooks.
#
# CPython raises these at the call site, so they are immune to both import
# timing and stale references. This is the layer the A3 recorder lacked.
# ---------------------------------------------------------------------------
def _any_frame_active() -> bool:
    """True if the recorder OR any extra consumer wants events.

    The tripwire attaches its own frame while the recorder plugin is
    idle. An earlier version of this guard checked only `_CURRENT`,
    which meant the audit hook returned early and dropped every event
    the tripwire needed. The scratch offender tests caught it: the
    ctypes test failed as expected and the network test silently
    passed. A guard that consults the wrong source of truth is worse
    than no guard, because it looks like it is working.
    """
    if _CURRENT["nodeid"] is not None:
        return True
    for frame in _CAPTURE_STACK:
        if frame["nodeid"] is not None:
            return True
    return False


def _audit_hook(event, args):
    # Audit hooks run for EVERY auditable operation in the process,
    # including every import and every file open. The first test must be
    # a frozenset membership check and nothing else.
    if event not in _AUDIT_WATCH:
        return
    if not _ACTIVE or not _any_frame_active():
        return
    try:
        if event == "subprocess.Popen":
            executable = args[0] if len(args) > 0 else None
            argv = args[1] if len(args) > 1 else None
            head = _argv_head(argv if argv is not None else executable)
            _record("process", {"api": "Popen", "exe": head[0] if head else "",
                                "argv": head, "source": "audit"})
        elif event == "os.system":
            command = str(args[0]) if args else ""
            _record("process", {"api": "os.system",
                                "exe": command.split()[0] if command.split() else "",
                                "argv": [command[:200]], "source": "audit"})
        elif event in ("os.exec", "os.fork", "os.posix_spawn"):
            _record("process", {"api": event, "exe": "",
                                "argv": [str(a)[:80] for a in args[:4]],
                                "source": "audit"})
        elif event == "os.startfile":
            _record("os_launch", {"api": "os.startfile",
                                  "path": str(args[0])[:200] if args else "",
                                  "source": "audit"})
        elif event in ("socket.getaddrinfo", "socket.gethostbyname",
                       "socket.gethostbyname_ex"):
            host = str(args[0]) if args else ""
            port = args[1] if len(args) > 1 else ""
            _record("network", {"api": event, "host": host,
                                "port": str(port), "loopback": is_loopback(host),
                                "source": "audit"})
        elif event == "socket.connect":
            address = args[1] if len(args) > 1 else None
            host, port = _split_address(address)
            _record("network", {"api": "socket.connect", "host": host,
                                "port": str(port), "loopback": is_loopback(host),
                                "source": "audit"})
        elif event in ("socket.sendto", "socket.sendmsg"):
            host, port = _split_address(args[0] if args else None)
            _record("network", {"api": event, "host": host, "port": str(port),
                                "loopback": is_loopback(host), "source": "audit"})
        elif event == "ctypes.dlopen":
            _record("dll_load", {"api": "ctypes.dlopen",
                                 "dll": str(args[-1])[:120], "source": "audit"})
        elif event == "ctypes.dlsym":
            _record("dll_load", {"api": "ctypes.dlsym",
                                 "dll": str(args[-2])[:120] if len(args) > 1 else "",
                                 "symbol": str(args[-1])[:120], "source": "audit"})
        elif event == "ctypes.call_function":
            # Does not exist on CPython 3.12. Listed so that if a future
            # interpreter adds it, the layer picks it up with no edit.
            _record("ctypes_call", {"api": "ctypes.call_function",
                                    "target": str(args[0])[:120] if args else "",
                                    "source": "audit"})
    except Exception:
        # An audit hook that raises can break unrelated code. It must not.
        return


def _argv_head(argv) -> list:
    try:
        if isinstance(argv, (list, tuple)):
            return [str(x)[:80] for x in list(argv)[:6]]
        if isinstance(argv, (str, bytes, os.PathLike)):
            return [str(argv)[:200]]
        return [str(argv)[:80]]
    except Exception:
        return []


def _split_address(address):
    try:
        if isinstance(address, tuple) and address:
            return str(address[0]), address[1] if len(address) > 1 else ""
        if isinstance(address, (str, bytes)):
            return str(address), ""
        return "", ""
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Layer 2: ctypes window calls.
#
# `ctypes.dlopen`/`ctypes.dlsym` fire once per library, not per call, so
# they cannot distinguish "imported user32" from "asked user32 a question".
# There is no `ctypes.call_function` audit event in CPython 3.12, so the
# observation point is the DLL attribute lookup, which every call in this
# codebase goes through (`ctypes.windll.user32.GetForegroundWindow()`).
# ---------------------------------------------------------------------------
class _RecordedCFunc:
    """Transparent proxy for a ctypes foreign function.

    Attribute writes are forwarded to the real function so the ctypes
    protocol (`restype`, `argtypes`, `errcheck`) still works after
    retrieval -- `u.GetSystemMetrics.restype = X` must reach the real
    function, not a dead attribute on this proxy.
    """

    __slots__ = ("_fn", "_label")

    def __init__(self, fn, label):
        object.__setattr__(self, "_fn", fn)
        object.__setattr__(self, "_label", label)

    def __call__(self, *a, **k):
        _record("ctypes_call", {"api": self._label, "source": "ctypes"})
        return self._fn(*a, **k)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_fn"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_fn"), name, value)

    def __repr__(self):
        return f"<recorded {self._label} {self._fn!r}>"


def _install_ctypes_layer():
    global _ACTIVE
    import ctypes

    if _INSTALL_STATE["ctypes"]:
        return
    if not hasattr(ctypes, "CDLL") or not hasattr(ctypes.CDLL, "__getattr__"):
        return

    original_getattr = ctypes.CDLL.__getattr__
    original_getitem = ctypes.CDLL.__getitem__

    def rec_getattr(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        fn = original_getitem(self, name)
        if not callable(fn) or getattr(fn, "__genesis_recorded__", False):
            return fn
        label = f"{_dll_name(self)}.{name}"
        wrapped = _RecordedCFunc(fn, label)
        # Mirror CDLL.__getattr__'s own caching, so the second access does
        # not re-enter this hook and the recorded wrapper stays installed.
        setattr(self, name, wrapped)
        return wrapped

    def rec_getitem(self, name):
        fn = original_getitem(self, name)
        if callable(fn) and not getattr(fn, "__genesis_recorded__", False):
            wrapped = _RecordedCFunc(fn, f"{_dll_name(self)}.{name}")
            setattr(self, name, wrapped)
            return wrapped
        return fn

    ctypes.CDLL.__getattr__ = rec_getattr
    ctypes.CDLL.__getitem__ = rec_getitem
    _INSTALL_STATE["ctypes"] = True
    _ACTIVE = True


def _dll_name(dll) -> str:
    try:
        return str(getattr(dll, "_name", None) or getattr(dll, "_handle", "dll"))
    except Exception:
        return "dll"


# ---------------------------------------------------------------------------
# Layer 3: post-import wrapping for the GUI and driver libraries.
#
# A meta_path finder delegates to the normal finders, then wraps the
# resolved loader's exec_module so the wrap happens when the module
# finishes loading. Import timing is exactly what defeated the A3
# recorder, which checked sys.modules at install time and found nothing.
# ---------------------------------------------------------------------------
WRAP_SPEC = {
    "win32gui": {
        "kind": "gui",
        "callables": None,  # every public callable
        "also_classes": False,
    },
    "win32api": {
        "kind": "gui",
        "callables": (
            "SetCursorPos", "GetCursorPos", "mouse_event", "keybd_event",
            "SetForegroundWindow", "GetForegroundWindow", "FindWindow",
            "FindWindowEx", "EnumWindows", "GetWindowText", "ShowWindow",
            "SetWindowPos", "MoveWindow", "SetWindowText", "PostMessage",
            "SendMessage", "GetWindowRect", "OpenClipboard", "SetClipboardData",
            "GetClipboardData", "EmptyClipboard", "RegisterHotKey",
        ),
        "also_classes": False,
    },
    "pyautogui": {
        "kind": "gui",
        "callables": (
            "click", "doubleClick", "rightClick", "tripleClick", "middleClick",
            "write", "typewrite", "press", "hotkey", "keyDown", "keyUp",
            "moveTo", "move", "dragTo", "drag", "scroll", "hscroll", "vscroll",
            "mouseDown", "mouseUp", "dragRel", "locate", "locateOnScreen",
        ),
        "also_classes": False,
    },
    "selenium.webdriver": {
        "kind": "browser",
        "callables": ("Chrome", "Firefox", "Edge", "Ie", "Safari", "Remote"),
        "also_classes": True,
    },
    "playwright.sync_api": {
        "kind": "browser",
        "callables": ("sync_playwright",),
        "also_classes": False,
    },
    "playwright.async_api": {
        "kind": "browser",
        "callables": ("async_playwright",),
        "also_classes": False,
    },
}


def _wrap_loaded_module(module_name: str) -> bool:
    spec = WRAP_SPEC.get(module_name)
    module = sys.modules.get(module_name)
    if spec is None or module is None:
        return False
    wrapped = []
    names = spec["callables"]
    for attr in _public_attrs(module, names):
        try:
            value = getattr(module, attr)
        except Exception:
            continue
        if isinstance(value, _ModuleProxy):
            continue
        if not callable(value):
            continue
        if spec["also_classes"] is False and isinstance(value, type):
            # A class we were not asked to wrap.
            if names is None:
                continue
        try:
            setattr(module, attr, _ModuleProxy(value, spec["kind"],
                                               f"{module_name}.{attr}"))
            wrapped.append(attr)
        except Exception:
            # Builtin or read-only attribute. Recorded, not fatal.
            _INSTALL_STATE["stale_bindings"].append(
                f"{module_name}.{attr} (not settable)")
    _INSTALL_STATE["wrapped_modules"].append(
        f"{module_name}: {len(wrapped)} wrapped")
    return bool(wrapped)


def _public_attrs(module, names) -> list:
    """The attributes worth wrapping for an eagerly-populated module."""
    if names is not None:
        return list(names)
    return [a for a in vars(module) if not a.startswith("_")]


def _install_lazy_attr_wrapper(module_name: str) -> bool:
    """Wrap a PEP 562 module ``__getattr__`` so lazy names are caught.

    selenium 4.48 resolves ``webdriver.Chrome`` through a module-level
    ``__getattr__``, so the name never appears in ``vars(module)``.
    Iterating only ``vars`` wrapped nothing -- the A3 failure, one layer
    down. Wrapping the ``__getattr__`` itself is also strictly better
    than forcing the attribute: reading it eagerly would import the
    chrome webdriver module at recorder-install time whether or not any
    test ever launched a browser.
    """
    spec = WRAP_SPEC.get(module_name)
    module = sys.modules.get(module_name)
    if spec is None or module is None:
        return False
    names = spec["callables"]
    if names is None:
        return False
    original = getattr(module, "__getattr__", None)
    if original is None or getattr(original, "__genesis_wrapped__", False):
        return False

    def lazy_getattr(attr):
        value = original(attr)
        if attr in names and callable(value) and not isinstance(value, _ModuleProxy):
            if spec["also_classes"] or not isinstance(value, type):
                wrapped = _ModuleProxy(value, spec["kind"],
                                       f"{module_name}.{attr}")
                # Cache the wrapper so the second access skips this path.
                try:
                    setattr(module, attr, wrapped)
                except Exception:
                    pass
                return wrapped
        return value

    lazy_getattr.__genesis_wrapped__ = True
    try:
        module.__getattr__ = lazy_getattr
    except Exception:
        return False
    _INSTALL_STATE["wrapped_modules"].append(
        f"{module_name}: lazy __getattr__ wrapped for {len(names)} names")
    return True


class _ModuleProxy:
    """Records a call, then calls through unchanged."""

    __slots__ = ("_fn", "_kind", "_label")

    def __init__(self, fn, kind, label):
        object.__setattr__(self, "_fn", fn)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_label", label)

    def __call__(self, *a, **k):
        _record(self._kind, {"api": self._label, "source": "module",
                             "args": _arg_preview(a)})
        return self._fn(*a, **k)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_fn"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_fn"), name, value)

    def __repr__(self):
        return f"<recorded {self._label} {self._fn!r}>"


def _arg_preview(a) -> list:
    try:
        return [str(x)[:60] for x in a[:3]]
    except Exception:
        return []


class _PostImportWrapper(importlib.abc.MetaPathFinder):
    """Wrap a target module's attributes once it has finished loading."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in WRAP_SPEC:
            return None
        # Delegate to the real finders, skipping this one, so import
        # resolution is unchanged.
        spec = None
        for finder in list(sys.meta_path):
            if finder is self:
                continue
            find = getattr(finder, "find_spec", None)
            if find is None:
                continue
            try:
                spec = find(fullname, path, target)
            except Exception:
                spec = None
            if spec is not None:
                break
        if spec is None or spec.loader is None:
            return None
        loader = spec.loader
        exec_module = getattr(loader, "exec_module", None)
        if exec_module is None or getattr(loader, "__genesis_wrapped__", False):
            return spec

        def wrapped_exec(module):
            exec_module(module)
            _wrap_loaded_module(fullname)
            _install_lazy_attr_wrapper(fullname)

        try:
            loader.exec_module = wrapped_exec
            loader.__genesis_wrapped__ = True
        except Exception:
            pass
        return spec


def _install_meta_path():
    if _INSTALL_STATE["meta_path"]:
        return
    for finder in sys.meta_path:
        if isinstance(finder, _PostImportWrapper):
            return
    sys.meta_path.insert(0, _PostImportWrapper())
    _INSTALL_STATE["meta_path"] = True


# ---------------------------------------------------------------------------
def _install_recorders():
    global _ACTIVE
    # Audit hooks cannot be removed once added, so install once per process
    # and gate on _ACTIVE for the rest of the session.
    if not _INSTALL_STATE["audit"]:
        sys.addaudithook(_audit_hook)
        _INSTALL_STATE["audit"] = True

    _ACTIVE = True
    _install_ctypes_layer()
    _install_meta_path()

    # Anything already imported before the recorder started.
    for module_name in list(WRAP_SPEC):
        if module_name in sys.modules:
            _wrap_loaded_module(module_name)
            _install_lazy_attr_wrapper(module_name)

    # NOTE: subprocess is deliberately NOT wrapped at module level. The
    # `subprocess.Popen` audit event fires inside Popen.__init__ itself, so
    # it catches every launch regardless of import timing or a stale
    # reference -- and replacing the class with a function breaks
    # `asyncio.windows_utils`, which does `class Popen(subprocess.Popen)`.
    # That was a measured transparency failure, not a hypothetical.
    #
    # NOTE: socket is likewise not wrapped at module level. The
    # `socket.getaddrinfo` and `socket.connect` audit events fire inside
    # the C implementation and already carry host, port and loopback.
    # Wrapping as well double-counted every lookup and, worse, emitted a
    # DIFFERENT event schema for the same action, so a consumer reading
    # `host`/`loopback` would KeyError on half the events.


def _wrap_socket_module():
    for attr, kind in (("getaddrinfo", "network"), ("gethostbyname", "network"),
                       ("create_connection", "network")):
        fn = getattr(socket, attr, None)
        if fn is None or getattr(fn, "__genesis_recorded__", False):
            continue
        setattr(socket, attr, _ModuleProxy(fn, kind, f"socket.{attr}"))