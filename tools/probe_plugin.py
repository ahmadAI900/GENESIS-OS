"""Opt-in pytest probe plugin: mechanically classify `live`-marked tests.

The fast gate missed real breakage three times because `live` was a
single bucket containing both "opens a real browser and talks to the
network" and "constructs GenesisOS and asserts on a return value".
This plugin decides the difference BY EXPERIMENT rather than by reading
tests.

Activate explicitly -- never in a normal run:

    pytest -m live -p probe_plugin --probe-network
    pytest -m live -p probe_plugin --probe-gui
    pytest -m live -p probe_plugin --probe-network --probe-gui

Interpretation (evidence, not judgement):

    fails under --probe-network        -> group (a) real network/model
    fails under --probe-gui            -> group (b) real browser/GUI/process
    passes under BOTH                  -> candidate (c) runtime-only

A test that passes because it skipped internally is NOT group (c); the
caller checks skip counts.

Design notes
------------
Blocking is installed only when a probe flag is present, so the plugin
is inert otherwise -- loading it changes nothing. Blocks raise, they do
not return None, so a test that genuinely needs the capability fails
loudly instead of silently degrading into a vacuous pass.

Modules are patched only if already imported, except socket and
subprocess which are always safe to patch. Optional GUI stacks
(pyautogui / win32gui / playwright / selenium) are patched lazily at
their real entry points, because importing them here would itself be a
side effect on a machine that does not have them.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# Modules whose PURPOSE is to start a user-visible process.
#
# VALIDATION STATUS 2026-10-09: THIS LIST DOES NOT YET WORK. Two
# configurations were tried and both failed validation in opposite
# directions:
#
#   broad list (incl. os_manager, runner, system_manager,
#   folder_manager, file_manager)
#       positive controls 9/9 fail   (correct)
#       negative control  FAILS       (false positive)
#
#   narrow list (genuine launchers only)
#       positive controls 4/9 fail   (false negatives - real notepad and
#                                     window tests stopped being caught)
#       negative control  FAILS       (still)
#
# Diagnosis: the real launch path transits the SAME aggregate modules
# (os_manager, system_manager) that ordinary test setup also uses. So
# module-name matching cannot separate "a test really opened notepad"
# from "a test constructed something that touches subprocess on the
# way through". No prefix list satisfies both controls.
#
# The broad list is retained because a classification instrument that
# MISSES real GUI tests is worse than one that over-reports: over-
# reporting only costs conservatism, under-reporting would let a real
# GUI test be marked runtime-only.
#
# A different method is needed. The obvious candidate is to stop
# inferring from blocking and start from an explicit declaration: each
# test marks what it needs, and the gate enforces the declaration
# rather than guessing at runtime.
LAUNCHER_MODULES = frozenset({
    "app_manager",
    "application_manager",
    "applications.app_manager",
    "network_manager",
    "folder_manager",
    "file_manager",
    "package_manager",
    "process_manager",
    "system_manager",
    "windows_registered_apps",
    "window_manager",
    "browser_manager",
    "os_manager",
    "runner",
    "media_control",
    "workstation_control",
})


class ProbeBlocked(RuntimeError):
    """Raised when a probe deliberately denies a capability."""


def pytest_addoption(parser):
    group = parser.getgroup("genesis-probes")
    group.addoption("--probe-network", action="store_true", default=False,
                    help="deny sockets; tests needing them become group (a)")
    group.addoption("--probe-gui", action="store_true", default=False,
                    help="deny process/GUI spawn; tests needing them become group (b)")


_BLOCKED_MESSAGE = (
    "genesis probe: this capability is deliberately denied to classify "
    "live-marked tests. Not a product failure."
)


def _install_network_probe():
    import socket

    def _deny(*args, **kwargs):
        raise ProbeBlocked(_BLOCKED_MESSAGE + " (network)")

    socket.socket.connect = _deny
    socket.socket.connect_ex = _deny
    socket.socket.sendto = _deny
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    socket.gethostbyname = _deny


def _install_gui_probe():
    """Block GENUINE GUI / browser / process-launch entry points.

    The first version of this probe patched ``subprocess.run`` and
    ``os.system`` globally. That was far too blunt: 47 tests already in
    the fast gate passed normally yet failed under it, because almost
    anything may touch subprocess incidentally -- a provider health
    check, a version probe, an import-time lookup. The instrument was
    producing false positives, and `test_pure_level3_objectives_do_not_
    invoke_agents` (a name that says it invokes nothing) was caught by
    it.

    The rule now: block the ENTRY POINTS of user-visible action, never
    the plumbing.

      * every pyautogui public action
      * win32gui window operations (constants are never touched)
      * playwright launch / selenium webdriver construction
      * os.startfile and ShellExecuteW/A
      * subprocess.Popen and subprocess.run ONLY when the calling frame
        belongs to a Genesis LAUNCHER_MODULE (below)

    That last rule is what removes the false positives: a health check
    calling subprocess from a provider module is allowed; a window
    manager spawning notepad is not.
    """

    import ctypes
    import inspect

    def _deny(name):
        def deny(*args, **kwargs):
            raise ProbeBlocked(
                _BLOCKED_MESSAGE + f" ({name})"
            )
        return deny

    # ---- pyautogui: the public action surface ------------------------
    pyautogui = sys.modules.get("pyautogui")
    if pyautogui is not None:
        for attr in ("click", "doubleClick", "rightClick", "write",
                     "typewrite", "press", "hotkey", "keyDown", "keyUp",
                     "moveTo", "dragTo", "scroll", "drag", "mouseDown",
                     "mouseUp"):
            if hasattr(pyautogui, attr):
                setattr(pyautogui, attr, _deny(f"pyautogui.{attr}"))

    # ---- win32gui: window operations, never constants -----------------
    win32gui = sys.modules.get("win32gui")
    if win32gui is not None:
        for attr in ("SetForegroundWindow", "FindWindow", "FindWindows",
                     "GetWindowText", "EnumWindows", "ShowWindow",
                     "SetWindowPos", "GetForegroundWindow",
                     "BringWindowToTop", "SetWindowText", "GetWindowRect",
                     "IsWindowVisible", "GetActiveWindow", "SetActiveWindow",
                     "SendMessage", "PostMessage", "MoveWindow"):
            if hasattr(win32gui, attr):
                setattr(win32gui, attr, _deny(f"win32gui.{attr}"))

    win32api = sys.modules.get("win32api")
    if win32api is not None:
        for attr in ("SetCursorPos", "mouse_event", "keybd_event"):
            if hasattr(win32api, attr):
                setattr(win32api, attr, _deny(f"win32api.{attr}"))

    # ---- browser launch ----------------------------------------------
    sync_api = sys.modules.get("playwright.sync_api")
    if sync_api is not None and hasattr(sync_api, "sync_playwright"):
        setattr(sync_api, "sync_playwright", _deny("playwright.sync_playwright"))
    playwright_mod = sys.modules.get("playwright.sync_api.sync_playwright")
    if playwright_mod is not None and hasattr(playwright_mod, "Playwright"):
        setattr(playwright_mod, "Playwright", _deny("playwright.Playwright"))
    webdriver = sys.modules.get("selenium.webdriver")
    if webdriver is not None:
        for attr in ("Chrome", "Firefox", "Edge", "Safari", "Ie"):
            if hasattr(webdriver, attr):
                setattr(webdriver, attr, _deny(f"selenium.webdriver.{attr}"))

    # ---- OS-level launches -------------------------------------------
    if hasattr(os, "startfile"):
        os.startfile = _deny("os.startfile")

    def _shell_execute_deny(*args, **kwargs):
        raise ProbeBlocked(_BLOCKED_MESSAGE + " (ShellExecuteW)")
    for windll_name in ("shell32", "Shell32"):
        windll = getattr(ctypes, windll_name, None)
        if windll is not None and hasattr(windll, "ShellExecuteW"):
            windll.ShellExecuteW = _shell_execute_deny

    # ---- process launch, scoped by call site --------------------------
    def _in_launcher_module() -> bool:
        frame = inspect.currentframe()
        # Walk out of this probe first.
        while frame is not None and frame.f_globals.get("__name__") == __name__:
            frame = frame.f_back
        while frame is not None:
            module_name = frame.f_globals.get("__name__", "")
            if any(module_name == n or module_name.endswith("." + n)
                   for n in LAUNCHER_MODULES):
                return True
            frame = frame.f_back
        return False

    real_popen = subprocess.Popen

    def guarded_popen(*args, **kwargs):
        if _in_launcher_module():
            raise ProbeBlocked(
                _BLOCKED_MESSAGE + " (subprocess.Popen from a launcher module)"
            )
        return real_popen(*args, **kwargs)

    subprocess.Popen = guarded_popen

    real_run = subprocess.run

    def guarded_run(*args, **kwargs):
        if _in_launcher_module():
            raise ProbeBlocked(
                _BLOCKED_MESSAGE + " (subprocess.run from a launcher module)"
            )
        return real_run(*args, **kwargs)

    subprocess.run = guarded_run


def pytest_configure(config):
    if config.getoption("--probe-network", default=False):
        _install_network_probe()
    if config.getoption("--probe-gui", default=False):
        _install_gui_probe()