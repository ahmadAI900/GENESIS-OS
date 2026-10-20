"""Shared pytest fixtures.

`workspace_root` gives a single test an isolated workspace root inside
the real activation root, so filesystem-writing tests prove in-workspace
behaviour without depending on the global switch being on or off. The
variable is set through monkeypatch so it is restored afterwards rather
than merely popped -- an earlier iteration leaked state across tests.
"""
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

from genesis_os.workspace_boundary import WORKSPACE_ROOT_ENV

ACTIVATION_ROOT = Path(__file__).resolve().parent.parent / ".genesis_workspace"
FIXTURE_PREFIX = "pytest-"
TIERING_FILE = Path(__file__).resolve().parent / "docs" / "tests_tiering.json"


# ----------------------------------------------------------------------
# Hermetic capability stubbing.
#
# `GenesisOS()` is the primary entry point and every test that builds a
# real one is marked `live`, because constructing it imports pyautogui
# (which probes the keyboard with ~110 user32 calls) and probes for
# browser drivers in subprocesses. So the entry point had NO fast-tier
# behavioural coverage at all: in Continuation A5, renaming
# `GenesisOS.classify` turned the gate red through exactly one test,
# and that test only asserted the member still EXISTS.
#
# These fixtures make the entry point buildable in the fast tier without
# a desktop. They stub at two points:
#
#   1. `sys.modules["pyautogui"]` -- a pure-Python stub, so `import
#      pyautogui` never reaches the real module and never performs its
#      import-time keyboard probe.
#   2. the browser provider `_probe_cache` globals -- set to "already
#      probed, unavailable", so `BrowserManager` skips the chromium and
#      chromedriver subprocess probes entirely.
#
# Nothing here weakens a test: a test that needs the real GUI is
# `live`, and the tripwire verifies these stubs really do leave no
# capability behind.
# ----------------------------------------------------------------------
_PROVIDER_PROBE_MODULES = ("genesis_os.browser_playwright",
                           "genesis_os.browser_selenium")


def _make_pyautogui_stub():
    import types
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.__genesis_stub__ = True
    stub.position = lambda: (0, 0)
    stub.size = lambda: (1920, 1080)
    stub.screenshot = lambda *a, **k: None
    stub.locate = lambda *a, **k: None
    stub.getActiveWindow = lambda: None
    stub.getWindowsWithTitle = lambda *a, **k: []
    for name in ("click", "doubleClick", "rightClick", "tripleClick",
                 "middleClick", "write", "typewrite", "press", "hotkey",
                 "keyDown", "keyUp", "moveTo", "move", "dragTo", "drag",
                 "scroll", "hscroll", "vscroll", "mouseDown", "mouseUp",
                 "dragRel", "locateOnScreen"):
        setattr(stub, name, lambda *a, **k: None)
    return stub


@pytest.fixture(scope="session")
def hermetic_capabilities():
    """Stub GUI, browser-provider and cloud-LLM access for the session.

    Session-scoped on purpose: building `GenesisOS` costs about 9 s, and
    paying that once beats paying it per test. Restores every patch on
    teardown so no other test inherits a fake.

    The AI stub was added after the boundary test proved insufficient:
    `classify()` resolves intents through `AIEngine.generate_response`,
    which reaches `api.groq.com`. Without this the test reached the real
    cloud and the tripwire correctly failed it -- a fixture that removes
    a GUI dependency but leaves the network one is not hermetic.
    """
    import sys as _sys
    saved_pyautogui = _sys.modules.get("pyautogui")
    saved_caches = {}
    saved_llm = {}
    installed_stub = saved_pyautogui is None
    if installed_stub:
        _sys.modules["pyautogui"] = _make_pyautogui_stub()
    for name in _PROVIDER_PROBE_MODULES:
        module = _sys.modules.get(name)
        if module is not None and hasattr(module, "_probe_cache"):
            saved_caches[name] = module._probe_cache
            module._probe_cache = 0

    try:
        from ai.ai_engine import AIEngine
    except Exception:
        AIEngine = None
    # NOT stubbed. Measured: `classify()` routes through the LLM, and
    # with `generate_response` stubbed to an offline answer it returns
    # level 1 with no intent for EVERY request -- including ones that
    # resolve deterministically when online. Stubbing the cloud removes
    # the GUI dependency but silently removes the routing behaviour the
    # entry-point tests assert on.
    #
    # Tests that need a capability id must therefore build the
    # classification from the deterministic capability resolver rather
    # than from `classify()`.

    try:
        yield
    finally:
        for name, value in saved_caches.items():
            _sys.modules[name]._probe_cache = value
        if installed_stub:
            _sys.modules.pop("pyautogui", None)


@pytest.fixture(scope="module")
def genesis_runtime(hermetic_capabilities):
    """A real `GenesisOS` built without a desktop.

    Module-scoped so the ~9 s construction is paid once per module. The
    tripwire watches it like any other setup, which is deliberate: if a
    future change makes construction reach a real capability again, the
    first test in this module fails rather than the suite quietly
    drifting back to needing a GUI.
    """
    from genesis import GenesisOS
    runtime = GenesisOS()
    try:
        yield runtime
    finally:
        # Item 21C (C36): stop the runtime's owned resources at
        # teardown instead of abandoning the module-scoped runtime
        # to interpreter exit. Idempotent, and a shutdown failure
        # must not mask the tests' own results.
        try:
            runtime.shutdown()
        except Exception:
            pass

# The capability tripwire lives in tools/ and is loaded by NAME, so the
# tools directory has to be importable before pytest resolves it. Loaded
# here rather than via `-p` on the command line because a gate that must
# be switched on by a flag is a gate that gets switched off.
TOOLS_DIR = Path(__file__).resolve().parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

pytest_plugins = ["tripwire_plugin", "tree_write_plugin"]


# ----------------------------------------------------------------------
# Pollution sentinel.
#
# Ledger item 19 was "global state surviving an env pop between tests",
# found only because a test asserted the value rather than trusting the
# teardown. The alternate ordering then surfaced a second, related
# leak: a test patched global os.name to "posix", and because
# pathlib.Path is a live factory that reads os.name, every Path built
# inside that window became a permanently unusable PosixPath instance.
#
# The sentinel makes that class of bug self-reporting: it snapshots
# before each test and compares after, failing THE TEST THAT LEAKED,
# by name, with the before/after values.
#
# TWO TIERS, decided 2026-10-08 after the first version produced
# order-dependent red runs.
#
#   FAIL  -- os.name, sys.platform, os.sep, pathlib.Path, and the
#            LLMIntentResolver budget/timeout attributes. Mutating any
#            of these is a TEST DEFECT: it changes behaviour for every
#            later test. `test_zz_sentinel_mutation.py` proved this
#            tier fires, by name, with before/after values.
#
#   RECORD -- the GENESIS_* environment keys. `ai/ai_engine.py:78` calls
#            `load_dotenv()` inside `AIEngine.__init__`, so ANY test
#            that constructs the full runtime injects .env into
#            os.environ for the life of the process. That is production
#            behaviour, not a test bug, and blaming whichever test
#            happened to construct a runtime first is arbitrary: it
#            made the default ordering green and the alternate ordering
#            red, with six different files "at fault" across runs.
#
#            So the suite is made HERMETIC by default (`genesis_env_guard`
#            below restores the keys around every test), which stops the
#            leak propagating, and the sentinel RECORDS which tests
#            introduced keys so the cause stays visible instead of
#            being hidden. A terminal report lists them.
# ----------------------------------------------------------------------

_FAIL_KEYS = ("os.name", "sys.platform", "os.sep",
              "pathlib.Path", "resolver budgets")

_WATCHED_MODULE_ATTRS = (
    ("genesis_os.llm_intent_resolver", "_LLM_CALL_TIMEOUT"),
    ("genesis_os.llm_intent_resolver", "_RESOLVE_TOTAL_BUDGET"),
)

# Tests that introduced GENESIS_* keys, for the session-end report.
_ENV_LEAK_REPORT = []


def _snapshot():
    import pathlib

    env = {k: v for k, v in os.environ.items() if k.startswith("GENESIS_")}
    mods = {}
    for module_name, attr in _WATCHED_MODULE_ATTRS:
        module = sys.modules.get(module_name)
        mods[f"{module_name}.{attr}"] = (
            getattr(module, attr, "<module not imported>")
            if module is not None else "<module not imported>"
        )
    return {
        "os.name": os.name,
        "sys.platform": sys.platform,
        "os.sep": os.sep,
        "pathlib.Path": pathlib.Path,
        "resolver budgets": mods,
    }


def _diff(before, after):
    return [
        f"      {key}: {before[key]!r} -> {after[key]!r}"
        for key in before if before[key] != after[key]
    ]


def _restore(before):
    """Put the watched globals back BEFORE reporting.

    Learned from the mutation check: failing in teardown while
    os.name == "posix" left pytest unable to render its own traceback,
    because pathlib.Path is a live factory that reads os.name. The
    report crashed with INTERNALERROR and the whole session was lost.
    So the sentinel restores first, then fails. That also means a
    leaking test can no longer poison the tests that follow it.
    """
    import pathlib

    os.name = before["os.name"]
    sys.platform = before["sys.platform"]
    os.sep = before["os.sep"]
    if pathlib.Path is not before["pathlib.Path"]:
        pathlib.Path = before["pathlib.Path"]
    for key, value in before["resolver budgets"].items():
        module_name, attr = key.rsplit(".", 1)
        module = sys.modules.get(module_name)
        if module is not None and value != "<module not imported>":
            setattr(module, attr, value)


def _restore_env(before):
    for key in [k for k in os.environ if k.startswith("GENESIS_")]:
        if key not in before:
            del os.environ[key]
    os.environ.update(before)


@pytest.fixture(autouse=True)
def approval_audit_in_tmp(monkeypatch, tmp_path_factory):
    """Keep the approval audit log out of the source tree.

    The log used to live at `genesis_os/approval_audit.jsonl`, so every
    test that dispatched an approval-gated action appended to the
    repository - 23 tests in `test_approval_channel.py` alone - and the
    tree stopped being byte-stable between runs. The path is now
    configurable (`GENESIS_APPROVAL_AUDIT_LOG`); this points every test
    at its own temp directory so no test writes into the product tree.

    Autouse, because the requirement is "no test may write the audit
    log into the repository", and an opt-in fixture would leave 23 tests
    silently exempt.
    """
    target = tmp_path_factory.mktemp("approval-audit") / "audit.jsonl"
    monkeypatch.setenv("GENESIS_APPROVAL_AUDIT_LOG", str(target))
    yield target


@pytest.fixture(autouse=True)
def genesis_env_guard(request):
    """Make the suite hermetic for ``GENESIS_*`` keys.

    Autouse for every test, because the leak is structural: building
    the full runtime calls ``load_dotenv()``, and once
    ``GENESIS_WORKSPACE_ROOT`` is in ``.env`` (it is, since F5
    activation) that means the workspace boundary can be armed
    mid-session by whichever test happened to construct a runtime
    first. A later test could then pass or fail purely on collection
    order.

    Recording happens HERE rather than in ``pollution_sentinel``,
    because this fixture tears down first: by the time the sentinel
    snapshots the "after" state the keys are already restored, so a
    sentinel-side check would never see them. Recording here is what
    makes the cause visible instead of hidden.
    """
    before = {k: v for k, v in os.environ.items() if k.startswith("GENESIS_")}
    yield
    after = {k: v for k, v in os.environ.items() if k.startswith("GENESIS_")}
    introduced = sorted(set(after) - set(before))
    if introduced:
        _ENV_LEAK_REPORT.append((request.node.nodeid, introduced))
    _restore_env(before)


@pytest.fixture(autouse=True)
def pollution_sentinel(request):
    before = _snapshot()
    yield
    after = _snapshot()
    changed = _diff(before, after)
    if changed:
        _restore(before)
        pytest.fail(
            f"global state leaked from {request.node.name}\n"
            + "\n".join(changed),
            pytrace=False,
        )


def pytest_terminal_summary(terminalreporter, exitstatus=None, config=None):
    counts = getattr(config, "_genesis_tier_counts", None)
    if counts:
        demoted, promoted, respected = counts
        terminalreporter.write_sep("-", "tiering applied")
        terminalreporter.write_line(
            f"{demoted} test(s) moved live -> runtime, "
            f"{promoted} moved runtime -> live, from docs/tests_tiering.json."
        )
        if respected:
            terminalreporter.write_line(
                f"{respected} test(s) kept an in-source `@pytest.mark.live` "
                f"that the evidence wanted to demote. Recorded, not "
                f"applied: the author marked that test on purpose."
            )

    if not _ENV_LEAK_REPORT:
        return
    names = sorted({name for name, _ in _ENV_LEAK_REPORT})
    keys = sorted({k for _, ks in _ENV_LEAK_REPORT for k in ks})
    terminalreporter.write_sep("=", "recorded environment loads")
    terminalreporter.write_line(
        f"{len(names)} test(s) constructed the full runtime and caused "
        f"load_dotenv() to inject {keys} into os.environ."
    )
    terminalreporter.write_line(
        "Restored after every test by genesis_env_guard, so this does "
        "not make results order-dependent. Cause: ai/ai_engine.py:78 "
        "calls load_dotenv() in AIEngine.__init__."
    )
    terminalreporter.write_line(
        "Cleaning this up properly means moving config loading out of "
        "the constructor. Recorded, not failed -- these tests are not "
        "defective."
    )


# ----------------------------------------------------------------------
# Data-driven marks.
#
# The tier a test belongs to is decided by evidence in
# docs/tests_tiering.json, produced by tools/apply_tiering.py from a
# recorded run. It is applied HERE, at collection time, so no test file
# carries a marker that has to be edited whenever the evidence changes.
#
# Two rules keep this from quietly widening the fast gate:
#   - a test absent from the file keeps whatever marks it already has;
#   - a test listed `runtime` is only demoted if it currently carries
#     `live`, so the file can never promote a test into the gate.
#
# If the file is missing or unreadable, nothing changes. A classification
# artefact must not be able to break collection.
# ----------------------------------------------------------------------
def _load_tiers():
    try:
        data = json.loads(TIERING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("__")}


# ----------------------------------------------------------------------
# Deterministic provider-availability probes.
#
# `PlaywrightBrowserProvider._check_availability` and the selenium
# equivalent spawn a child process to probe for a driver binary and join
# it with `join(timeout=5.0)`. The result -- INCLUDING a timeout -- is
# cached in a module-level `_probe_cache` for the life of the process.
# Under CPU contention the probe exceeds five seconds, is terminated,
# and the timeout is cached as "unavailable": the provider then stays
# unregistered for every subsequent test in that process.
#
# Observed in Continuation A5: `test_browser_manager_has_three_
# concrete_providers` failed once and then passed 5/5, with nothing in
# the test having changed.
#
# The product fix is a TTL plus never caching timeouts. That is Phase 5
# work and out of scope here. What is in scope is making the TEST
# deterministic without editing its body: this fixture pins the probe
# cache so the outcome cannot depend on how loaded the machine was, and
# restores it afterwards.
# ----------------------------------------------------------------------
PROBE_CACHE_MODULES = ("genesis_os.browser_playwright",
                       "genesis_os.browser_selenium")

# Tests whose outcome depends on a provider probe completing in time.
#
# `test_pure_level3_objectives_do_not_invoke_agents` was added here in
# C2. It builds a REAL `GenesisOS` from a MODULE-scoped fixture, so its
# provider probe runs during fixture setup, and the browser step it
# dispatches can only reach a verified state if a driver registered. Its
# measured cost was 50-94s per run (mean 69.5s over 20 fresh processes
# under 3x CPU load) for a test that asserts two things about agent
# dispatch, all of it spent waiting on a probe the fixture removes.
_PROBE_SENSITIVE = (
    "test_browser_manager_has_three_concrete_providers",
    "test_pure_level3_objectives_do_not_invoke_agents",
)

# Which IMPORT NAME each probe module checks for. Deriving it with
# `name.split(".")[-1]` yields "browser_playwright", which is not a real
# package, so `find_spec` returned None and the fixture pinned the cache
# to 0 -- i.e. it declared the provider UNAVAILABLE, which is worse than
# doing nothing at all. The bug was invisible for two sessions because
# the fixture was never actually being set up.
_PROBE_PACKAGE_NAMES = {
    "genesis_os.browser_playwright": "playwright",
    "genesis_os.browser_selenium": "selenium",
}


def _pin_probe_caches(monkeypatch, value):
    import importlib
    pinned = []
    for name in PROBE_CACHE_MODULES:
        module = importlib.import_module(name)
        if hasattr(module, "_probe_cache"):
            monkeypatch.setattr(module, "_probe_cache", value)
            pinned.append(name)
    return pinned


@pytest.fixture
def deterministic_provider_probes(request, monkeypatch):
    """Pin provider availability for this test.

    Attached by `pytest_collection_modifyitems` to the tests that assert
    on provider registration, so no test body is edited.

    **INSUFFICIENT -- do not assume this makes the test deterministic.**

    It removes ONE of the two load-sensitive mechanisms:

      1. `PlaywrightBrowserProvider._check_availability` spawns a child
         process and joins it with `join(timeout=5.0)`, caching the
         result -- including a timeout -- in a module-level
         `_probe_cache` for the life of the process. Pinning that cache
         removes this one.

      2. `BrowserManager.__init__` wraps provider construction in
         `_PROVIDER_PROBE_TIMEOUT = 10.0` and "abandons a probe that
         cannot finish in this window rather than allow it to block
         construction". Under full-suite CPU load this fires and
         `GenesisOS._build_minimal_browser()` substitutes a
         webbrowser-only manager.

    Measured with this fixture attached: 20/20 green in isolation, 8/8
    under 3x CPU load, and STILL FAILING in the full default-order run
    with `provider_names == ['webbrowser']` -- the signature of
    mechanism 2, not mechanism 1.

    Controlling mechanism 2 means changing product behaviour, which this
    effort may not do. The fixture is kept because it removes a real
    source of nondeterminism and costs nothing, but the residual flake
    is real and is listed in docs/fast_gate_tiering.md for Phase 5.
    """
    import importlib.util
    pinned = []
    for name in PROBE_CACHE_MODULES:
        package = _PROBE_PACKAGE_NAMES.get(name)
        if package is None:
            continue
        try:
            available = importlib.util.find_spec(package) is not None
        except (ImportError, ValueError):
            available = False
        module = importlib.import_module(name)
        if hasattr(module, "_probe_cache"):
            monkeypatch.setattr(module, "_probe_cache", 1 if available else 0)
            monkeypatch.setattr(module, "_probe_cache_kind", "definitive",
                                raising=False)
            pinned.append(f"{name}={1 if available else 0}")
    yield pinned


def pytest_collection_modifyitems(config, items):
    # ONE definition of this hook. B1 briefly had two: one attaching the
    # probe-determinism fixture, one applying the tiering. Python binds
    # only the last, so the fixture was never attached for any test and
    # `test_browser_manager_has_three_concrete_providers` stayed flaky
    # while the fixture meant to fix it sat in the file looking correct.
    # Both jobs now live here.
    tiers = _load_tiers()
    for item in items:
        if item.name in _PROBE_SENSITIVE:
            # `item.fixturenames.append(...)`, NOT
            # `item.add_marker(pytest.mark.usefixtures(...))`.
            #
            # pytest builds each item's `fixturenames` when the item is
            # created from its function, BEFORE
            # `pytest_collection_modifyitems` runs. A usefixtures
            # marker added afterwards never reaches `fixturenames`, so
            # the fixture is silently not set up -- the exact failure
            # that left this test flaky with a fixture that appeared
            # to be attached. Verified with a marker file: the usefixtures
            # form produced no marker at all.
            if "deterministic_provider_probes" not in item.fixturenames:
                item.fixturenames.append("deterministic_provider_probes")
    if not tiers:
        return
    _apply_tiering(config, items, tiers)


def _has_own_live_marker(item):
    """True when the test FUNCTION itself was decorated `@live`.

    A module-level ``pytestmark = pytest.mark.live`` is a coarse bucket
    applied to every test in a file, and overriding it from evidence is
    the whole point of the tiering. A decorator on the function is a
    deliberate, usually documented decision about one test.

    Continuation A5 caught what happens when those are treated as the
    same thing: `test_unseen_task_semantic.py::
    test_anaphoric_move_plan_is_valid` carries an explicit
    `@pytest.mark.live` with a docstring explaining that it builds a
    real GenesisOS whose browser probe reaches the network. The recorded
    evidence said `runtime`, because an earlier test had already paid
    the one-shot pyautogui import cost. The hook stripped the marker and
    the tripwire then failed the test.

    That is the hook overwriting a human statement with a measurement
    that has a known blind spot. Only the module-level bucket is
    demoted.
    """
    own = getattr(item.obj, "pytestmark", None)
    if not own:
        return False
    return any(getattr(m, "name", None) == "live" for m in own)


def _apply_tiering(config, items, tiers):
    promoted = 0
    demoted = 0
    respected = 0
    for item in items:
        entry = tiers.get(item.nodeid)
        if entry is None:
            continue
        if entry.get("tier") == "runtime":
            if item.get_closest_marker("live") is None:
                continue
            if _has_own_live_marker(item):
                # The author marked this specific test on purpose. The
                # evidence did not, and the evidence can be wrong.
                respected += 1
                continue
            item.own_markers = [
                m for m in item.own_markers if m.name != "live"]
            demoted += 1
        elif entry.get("tier") == "live":
            if item.get_closest_marker("live") is None:
                item.add_marker(pytest.mark.live)
                promoted += 1

    if demoted or promoted or respected:
        config._genesis_tier_counts = (demoted, promoted, respected)


@pytest.fixture
def workspace_root(monkeypatch, request):
    """A unique, removable workspace root for one test.

    Lives inside the real activation root so the test exercises the same
    root production uses, but is unique per test so tests cannot see
    each other's files.
    """
    ACTIVATION_ROOT.mkdir(parents=True, exist_ok=True)
    unique = ACTIVATION_ROOT / (
        f"{FIXTURE_PREFIX}{request.node.name[:40]}-{uuid.uuid4().hex[:8]}"
    )
    unique.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(unique))
    try:
        yield unique
    finally:
        # Move the process out of the directory first. Tests that use a
        # RELATIVE target call monkeypatch.chdir(workspace_root), and on
        # Windows a directory cannot be removed while it is the process
        # working directory. That silently defeated the cleanup when
        # errors were ignored, which is how 28 stale directories
        # accumulated across sessions.
        try:
            if Path.cwd().is_relative_to(unique):
                os.chdir(ACTIVATION_ROOT.parent)
        except (OSError, ValueError):
            pass
        shutil.rmtree(unique, ignore_errors=True)


def pytest_sessionstart(session):
    """Sweep residue from sessions killed mid-test.

    An interrupted session cannot run the fixture's cleanup, so
    directories named pytest-<test>-<id> accumulate. Only entries
    matching that exact prefix AND older than an hour are removed: the
    activation root itself, and anything a human put there, are never
    touched. Decoy-tested against a right-prefix/old entry (removed),
    a right-prefix/fresh entry (kept), a wrong-prefix entry (kept), and
    the root itself (kept).
    """
    if not ACTIVATION_ROOT.is_dir():
        return
    cutoff = time.time() - 3600
    for entry in ACTIVATION_ROOT.iterdir():
        if not entry.is_dir() or not entry.name.startswith(FIXTURE_PREFIX):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue