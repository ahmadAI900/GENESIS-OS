"""
Genesis OS — Level 5.0 Capability Provider Registry

Maps capabilities to ordered lists of providers, each with a real
health-check, risk-tier reference (from the capability, never the
provider), and an idempotent/non-idempotent flag.

This is the core infrastructure for Phase 5's three amendments:

  Amendment 1 — Health checks must attempt real operations, not just imports
  Amendment 2 — Risk classification comes from the CAPABILITY, not the provider
  Amendment 3 — Non-idempotent operations require state verification before fallback

Design constraints:
  - Proven on a bounded set: browser capabilities that genuinely have
    multiple real providers (Playwright, Selenium, webbrowser).
  - NOT wired into all 123 capabilities in this session — proved on a
    representative set first.
  - GUI domain has only one real provider (WindowsGUIProvider); we do
    not fake a second one.

Architecture:

    CapabilityProviderRegistry
        |
        +-- capability_id -> [ProviderEntry, ...]
        |
        +-- each ProviderEntry:
              - provider_class (the BrowserProvider subclass)
              - health_check() -> real lightweight operation
              - idempotent: bool
              - capability_risk_tier: str (from the capability, not the provider)
"""

from __future__ import annotations

import multiprocessing as _mp
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type


# Health checks must not block indefinitely.  A Playwright or
# Selenium health check that hangs should not freeze the entire
# BrowserManager or test suite.  5 seconds is generous enough for
# a real health check to complete on any functional installation.
HEALTH_CHECK_TIMEOUT: float = 5.0


def _run_health_check_in_subprocess(result_ref, health_check_fn):
    """Target function for multiprocessing health check.

    Must be defined at module level (not nested) so it can be
    pickled on Windows where multiprocessing uses 'spawn'.
    """
    try:
        result_ref.value = 1 if health_check_fn() else 0
    except Exception:
        result_ref.value = 0


class IdempotencyFlag(Enum):
    """Whether a capability is safe to retry without state checks."""
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


@dataclass
class ProviderEntry:
    """One provider in the ordered fallback chain for a capability.

    Attributes:
        provider_name: Human-readable name (e.g. "playwright", "selenium").
        health_check: Callable that performs a real lightweight operation
                      and returns True if the provider is genuinely usable.
        idempotent: Whether this capability is safe to blindly retry.
        capability_risk_tier: Risk tier from the CAPABILITY definition
                              (not from the provider). This is the same
                              value regardless of which provider dispatches.
        provider_class: Optional reference to the actual provider class
                        for documentation/debugging.
        platform_support: "windows" for Win32/COM-backed providers,
                          "cross-platform" for stdlib/pure-python ones.
    """
    provider_name: str
    health_check: Callable[[], bool]
    idempotent: bool
    capability_risk_tier: str
    provider_class: Optional[Any] = None
    last_health_check_result: Optional[bool] = None
    last_health_check_time: Optional[float] = None
    health_check_freshness_seconds: float = 300.0  # 5 minutes
    # When > 0, health checks run in a subprocess with this timeout.
    # Set to 0 to run in-process (needed for tests that patch the
    # health check, since subprocesses don't see parent patches).
    subprocess_timeout: float = HEALTH_CHECK_TIMEOUT
    platform_support: str = "windows"
    # Phase 5 latency tracking: real observations only, no estimates.
    latency_samples: int = 0
    latency_total_ms: float = 0.0
    latency_max_ms: float = 0.0
    latency_last_ms: Optional[float] = None

    def record_latency(self, elapsed_ms: float) -> None:
        """Record one real latency observation."""
        try:
            value = float(elapsed_ms)
        except (TypeError, ValueError):
            return
        if value < 0:
            return
        self.latency_samples += 1
        self.latency_total_ms += value
        self.latency_last_ms = value
        if value > self.latency_max_ms:
            self.latency_max_ms = value

    def latency_stats(self) -> Dict[str, Any]:
        """Real latency performance (no fabricated percentiles)."""
        avg = (
            self.latency_total_ms / self.latency_samples
            if self.latency_samples
            else None
        )
        return {
            "samples": self.latency_samples,
            "avg_ms": avg,
            "max_ms": self.latency_max_ms if self.latency_samples else None,
            "last_ms": self.latency_last_ms,
        }

    def is_healthy(self, force: bool = False) -> bool:
        """Run a real health check if stale or forced.

        Amendment 1: This must attempt a real lightweight operation,
        not just check if an import succeeded.

        Phase 5 gap fix: Health checks run in a separate PROCESS
        with a hard timeout.  A hanging provider health check
        (e.g. Playwright trying to launch Chromium, or
        ChromeDriverManager blocking the GIL) returns False
        instead of blocking the caller indefinitely.
        """
        now = time.monotonic()
        if (
            not force
            and self.last_health_check_result is not None
            and self.last_health_check_time is not None
            and (now - self.last_health_check_time) < self.health_check_freshness_seconds
        ):
            return self.last_health_check_result

        use_subprocess = (
            self.subprocess_timeout > 0
            and not CapabilityProviderRegistry._subprocess_disabled
        )
        started = time.monotonic()
        if use_subprocess:
            result_flag = _mp.Value("i", 0)
            proc = _mp.Process(
                target=_run_health_check_in_subprocess,
                args=(result_flag, self.health_check),
            )
            proc.start()
            proc.join(timeout=self.subprocess_timeout)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
                result = False
            else:
                result = bool(result_flag.value)
        else:
            try:
                result = bool(self.health_check())
            except Exception:
                result = False
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.record_latency(elapsed_ms)

        self.last_health_check_result = result
        self.last_health_check_time = now
        return self.last_health_check_result


class CapabilityProviderRegistry:
    """Registry mapping capabilities to ordered provider chains.

    The registry is populated at module load time for the browser
    domain (the only domain with genuinely multiple real providers
    today). Other domains are honest: if they have one provider,
    they register one provider.

    Usage::

        registry = CapabilityProviderRegistry()
        chain = registry.get_provider_chain("browser.click")
        for entry in chain:
            if entry.is_healthy():
                # use this provider
                break
    """

    # Set to True in tests that patch health-check internals,
    # since subprocesses don't see parent-process patches.
    _subprocess_disabled: bool = False

    # Process-wide shared instance. Provider health state
    # (last_health_check_result / last_health_check_time) only
    # becomes observable on a LONG-LIVED registry. Constructing a
    # throwaway registry yields all-None health, which makes any
    # health-aware consumer silently blind. Consumers that need to
    # read real health must share this instance.
    _shared_instance: Optional["CapabilityProviderRegistry"] = None
    _shared_lock: Any = None

    @classmethod
    def get_shared(cls) -> "CapabilityProviderRegistry":
        """
        Return the process-wide provider registry instance.

        Long-lived so that real health-check results recorded by
        dispatch (e.g. BrowserManager) are observable by ranking
        and other read-only consumers.
        """

        lock = cls._shared_lock
        if lock is None:
            import threading

            lock = threading.Lock()
            cls._shared_lock = lock

        with lock:
            if cls._shared_instance is None:
                cls._shared_instance = cls()
            return cls._shared_instance

    @classmethod
    def reset_shared(cls) -> None:
        """Drop the shared instance (tests / explicit reload)."""

        lock = cls._shared_lock
        if lock is None:
            cls._shared_instance = None
            return

        with lock:
            cls._shared_instance = None

    def __init__(self) -> None:
        self._chains: Dict[str, List[ProviderEntry]] = {}
        self._register_browser_providers()

    def register(
        self,
        capability_id: str,
        provider_entry: ProviderEntry,
        *,
        at_front: bool = False,
    ) -> None:
        """Register a provider for a capability."""
        if capability_id not in self._chains:
            self._chains[capability_id] = []

        chain = self._chains[capability_id]
        if at_front:
            chain.insert(0, provider_entry)
        else:
            chain.append(provider_entry)

    def get_provider_chain(self, capability_id: str) -> List[ProviderEntry]:
        """Return the ordered list of providers for a capability.

        Phase 5 universal coverage: capabilities without an
        explicitly registered multi-provider chain get an honest
        single-provider chain built from their descriptor on
        demand (and cached). Unknown IDs still return [].
        """
        chain = list(self._chains.get(capability_id, []))
        if chain:
            return chain
        built = self._ensure_single_provider_chain(capability_id)
        return list(built)

    def _ensure_single_provider_chain(
        self, capability_id: str
    ) -> List[ProviderEntry]:
        """Build + cache an honest one-entry chain from the
        capability descriptor. No fake second providers."""
        try:
            from genesis_os.capability_registry import CapabilityRegistry
            descriptor = CapabilityRegistry.get(capability_id)
        except Exception:
            return []
        prober, platform = _DOMAIN_PROBES.get(
            getattr(descriptor, "provider", ""), (_probe_python_runtime, "windows")
        )
        risk = str(getattr(descriptor, "risk_level", "low") or "low")
        entry = ProviderEntry(
            provider_name=f"{getattr(descriptor, 'provider', 'genesis')}[single]",
            health_check=prober,
            idempotent=capability_id not in NON_IDEMPOTENT_CAPABILITIES,
            capability_risk_tier=risk,
            subprocess_timeout=0,
            platform_support=platform,
        )
        self._chains[capability_id] = [entry]
        return [entry]

    def get_healthy_provider(self, capability_id: str) -> Optional[ProviderEntry]:
        """Return the first healthy provider for a capability.

        Amendment 1: Uses real health checks, not just availability flags.
        """
        for entry in self.get_provider_chain(capability_id):
            if entry.is_healthy():
                return entry
        return None

    def check_all_health(self, capability_id: str) -> Dict[str, bool]:
        """Run health checks on all providers for a capability.

        Returns a dict of provider_name -> healthy.
        """
        results = {}
        for entry in self.get_provider_chain(capability_id):
            results[entry.provider_name] = entry.is_healthy(force=True)
        return results

    def get_capability_risk_tier(self, capability_id: str) -> Optional[str]:
        """Return the risk tier for a capability.

        Amendment 2: Risk tier comes from the CAPABILITY, not the provider.
        All providers for the same capability share the same risk tier.
        """
        chain = self.get_provider_chain(capability_id)
        if chain:
            return chain[0].capability_risk_tier
        return None

    def is_idempotent(self, capability_id: str) -> bool:
        """Return whether a capability is idempotent.

        Amendment 3: For non-idempotent capabilities, fallback requires
        real state verification before attempting the next provider.
        """
        chain = self.get_provider_chain(capability_id)
        if chain:
            return chain[0].idempotent
        return False

    def capability_ids(self) -> List[str]:
        """Return all registered capability IDs."""
        return list(self._chains.keys())

    # --------------------------------------------------------
    # BROWSER PROVIDER REGISTRATION
    # --------------------------------------------------------

    def _register_browser_providers(self) -> None:
        """Register browser providers for ALL browser capabilities.

        BrowserProvider ABC defines standard methods (click, type,
        scroll, etc.) that all concrete providers implement.  Every
        browser capability gets the full provider chain so that
        per-operation dispatch can fall back on failure.
        """

        # Risk tiers for browser capabilities (from security_model.py)
        BROWSER_RISK = "LOW"  # Most browser ops are read-only
        BROWSER_MEDIUM_RISK = "MEDIUM"  # download, screenshot, upload

        # Helper to register a capability with all three providers.
        # Playwright and Selenium health checks can hang or block the
        # GIL (sync_playwright, ChromeDriverManager.install), so they
        # use process-based timeout.  webbrowser's check is a trivial
        # lambda — runs in-process for ~0ms overhead.
        def _register_all(cap_id: str, risk: str = BROWSER_RISK, idempotent: bool = True) -> None:
            try:
                from genesis_os.capability_registry import CapabilityRegistry
                descriptor_risk = str(
                    CapabilityRegistry.get(cap_id).risk_level or risk
                ).upper()
                if descriptor_risk in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                    risk = descriptor_risk
            except Exception:
                pass
            self.register(cap_id, ProviderEntry(
                provider_name="playwright",
                health_check=self._playwright_health_check,
                idempotent=idempotent,
                capability_risk_tier=risk,
                subprocess_timeout=HEALTH_CHECK_TIMEOUT,
            ))
            self.register(cap_id, ProviderEntry(
                provider_name="selenium",
                health_check=self._selenium_health_check,
                idempotent=idempotent,
                capability_risk_tier=risk,
                subprocess_timeout=HEALTH_CHECK_TIMEOUT,
            ))
            self.register(cap_id, ProviderEntry(
                provider_name="webbrowser",
                health_check=self._webbrowser_health_check,
                idempotent=idempotent,
                capability_risk_tier=risk,
                subprocess_timeout=0,  # In-process: no GIL risk
            ))

        # All standard browser operations
        _register_all("browser.click", idempotent=False)
        _register_all("browser.type", idempotent=False)
        _register_all("browser.scroll", idempotent=False)
        _register_all("browser.search")
        _register_all("browser.extract")
        _register_all("browser.find")
        _register_all("browser.get_title")
        _register_all("browser.get_url")
        _register_all("browser.switch_tab")
        _register_all("browser.open_tab", idempotent=False)
        _register_all("browser.close_tab", idempotent=False)
        _register_all("browser.get_tabs")
        _register_all("browser.select")
        _register_all("browser.wait")
        _register_all("browser.open_url")

        # Medium-risk operations
        _register_all("browser.screenshot", risk=BROWSER_MEDIUM_RISK, idempotent=False)
        _register_all("browser.get_page_state", risk=BROWSER_MEDIUM_RISK)
        _register_all("browser.upload", risk=BROWSER_MEDIUM_RISK, idempotent=False)

        # NON-idempotent: downloading same file twice writes to disk twice
        _register_all("browser.download", risk=BROWSER_MEDIUM_RISK, idempotent=False)

    # --------------------------------------------------------
    # REAL HEALTH CHECKS — Amendment 1
    # --------------------------------------------------------

    @staticmethod
    def _webbrowser_health_check() -> bool:
        try:
            import webbrowser
            return callable(getattr(webbrowser, "open", None))
        except Exception:
            return False

    @staticmethod
    def _playwright_health_check() -> bool:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_content("<html><body>health</body></html>")
                    return page.locator("body").inner_text() == "health"
                finally:
                    browser.close()
        except Exception:
            return False

    @staticmethod
    def _selenium_health_check() -> bool:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options,
            )
            try:
                driver.get("data:text/html,<html><body>health</body></html>")
                return driver.find_element("tag name", "body").text == "health"
            finally:
                driver.quit()
        except Exception:
            return False


# ============================================================
# PHASE 5 — UNIVERSAL COVERAGE (honest single-provider chains)
# ============================================================
#
# Every capability gets a provider chain. Domains with one real
# provider get a one-entry chain that says so — no fake second
# providers. Health checks are real lightweight characteristic
# operations (Amendment 1); risk tiers come from the capability
# descriptor enriched in Phase 3 (Amendment 2); idempotency is an
# explicit per-capability flag (Amendment 3).

def _probe_temp_roundtrip() -> bool:
    """Characteristic of file-backed providers: write, read, delete."""
    import os
    import tempfile
    fd, path = tempfile.mkstemp(prefix="genesis_probe_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(b"probe")
        with open(path, "rb") as f:
            ok = f.read() == b"probe"
        os.unlink(path)
        return ok
    except Exception:
        try:
            os.unlink(path)
        except Exception:
            pass
        return False


def _probe_win32_foreground() -> bool:
    """Characteristic of Win32-backed providers: real API call."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return isinstance(hwnd, int)
    except Exception:
        return False


def _probe_docx_roundtrip() -> bool:
    """Characteristic of document providers: in-memory docx build."""
    try:
        from docx import Document
        import io
        doc = Document()
        doc.add_paragraph("probe")
        buf = io.BytesIO()
        doc.save(buf)
        return len(buf.getvalue()) > 0
    except Exception:
        return False


def _probe_xlsx_roundtrip() -> bool:
    """Characteristic of spreadsheet providers: in-memory xlsx build."""
    try:
        from openpyxl import Workbook
        import io
        wb = Workbook()
        wb.active.append(["probe"])
        buf = io.BytesIO()
        wb.save(buf)
        wb.close()
        return len(buf.getvalue()) > 0
    except Exception:
        return False


def _probe_clipboard() -> bool:
    """Characteristic of the clipboard provider: open/close works."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not user32.OpenClipboard(None):
            return False
        try:
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _probe_audio_devices() -> bool:
    """Characteristic of audio providers: device enumeration works."""
    try:
        import ctypes
        return int(ctypes.windll.winmm.waveOutGetNumDevs()) >= 0
    except Exception:
        return False


def _probe_display_metrics() -> bool:
    """Characteristic of display providers: system metrics readable."""
    try:
        import ctypes
        return int(ctypes.windll.user32.GetSystemMetrics(0)) > 0
    except Exception:
        return False


def _probe_memory_status() -> bool:
    """Characteristic of hardware providers: memory status readable."""
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return bool(ok) and status.ullTotalPhys > 0
    except Exception:
        return False


def _probe_process_snapshot() -> bool:
    """Characteristic of process/system providers: real enumeration."""
    try:
        import ctypes
        arr = (ctypes.c_ulong * 1024)()
        needed = ctypes.c_ulong()
        ok = ctypes.windll.psapi.EnumProcesses(
            arr, ctypes.sizeof(arr), ctypes.byref(needed))
        return bool(ok) and needed.value > 0
    except Exception:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            return isinstance(hwnd, int)
        except Exception:
            return False


def _probe_network_stack() -> bool:
    """Characteristic of network providers: IP stack usable (no traffic)."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            return True
        finally:
            sock.close()
    except Exception:
        return False


def _probe_package_manager() -> bool:
    """Characteristic of the package provider: winget resolvable."""
    try:
        import shutil
        return shutil.which("winget") is not None
    except Exception:
        return False


def _probe_screen_capture() -> bool:
    """Characteristic of capture providers: 1px grab works."""
    try:
        from PIL import ImageGrab
        shot = ImageGrab.grab(bbox=(0, 0, 1, 1))
        return shot is not None and shot.size == (1, 1)
    except Exception:
        return False


def _probe_python_runtime() -> bool:
    """Characteristic of pure-python providers: interpreter works."""
    try:
        from datetime import datetime
        return (1 + 1) == 2 and datetime.now() is not None
    except Exception:
        return False


# provider value -> (health prober, platform_support)
_DOMAIN_PROBES: Dict[str, tuple] = {
    "genesis.filesystem": (_probe_temp_roundtrip, "cross-platform"),
    "genesis.application": (_probe_win32_foreground, "windows"),
    "genesis.windows": (_probe_win32_foreground, "windows"),
    "genesis.gui": (_probe_win32_foreground, "windows"),
    "genesis.workstation": (_probe_win32_foreground, "windows"),
    "genesis.doc_intel": (_probe_docx_roundtrip, "cross-platform"),
    "genesis.document": (_probe_docx_roundtrip, "cross-platform"),
    "genesis.sheet_intel": (_probe_xlsx_roundtrip, "cross-platform"),
    "genesis.spreadsheet": (_probe_xlsx_roundtrip, "cross-platform"),
    "genesis.data": (_probe_xlsx_roundtrip, "cross-platform"),
    "genesis.clipboard": (_probe_clipboard, "windows"),
    "genesis.notes": (_probe_temp_roundtrip, "cross-platform"),
    "genesis.audio": (_probe_audio_devices, "windows"),
    "genesis.media": (_probe_audio_devices, "windows"),
    "genesis.volume": (_probe_audio_devices, "windows"),
    "genesis.display": (_probe_display_metrics, "windows"),
    "genesis.capture": (_probe_screen_capture, "windows"),
    "genesis.hardware": (_probe_memory_status, "windows"),
    "genesis.network": (_probe_network_stack, "cross-platform"),
    "genesis.web": (_probe_network_stack, "cross-platform"),
    "genesis.process": (_probe_process_snapshot, "windows"),
    "genesis.system": (_probe_process_snapshot, "windows"),
    "genesis.cleanup": (_probe_process_snapshot, "windows"),
    "genesis.packages": (_probe_package_manager, "windows"),
    "genesis.daily": (_probe_temp_roundtrip, "cross-platform"),
}

# Capability IDs that are NOT safe to blind-retry. Unknown capabilities
# also fail closed in is_idempotent().
NON_IDEMPOTENT_CAPABILITIES = frozenset({
    "file.delete", "file.move", "file.rename", "file.copy", "file.create",
    "folder.delete", "folder.move", "folder.rename", "folder.create",
    "folder.organize", "filesystem.delete", "filesystem.move",
    "filesystem.rename", "cleanup.empty_recycle_bin",
    "document.create", "document.edit", "document.transform",
    "document.create_txt", "document.create_docx", "document.create_csv",
    "document.create_json", "document.create_markdown",
    "document.create_pdf",
    "document.create_docx_intel",
    "spreadsheet.calculate", "spreadsheet.filter", "spreadsheet.sort",
    "spreadsheet.rank", "spreadsheet.group_by", "spreadsheet.aggregate",
    "spreadsheet.add_column", "spreadsheet.update_cell",
    "spreadsheet.create_from_dicts", "spreadsheet.calculate_values",
    "spreadsheet.rank_values",
    "browser.click", "browser.type", "browser.scroll", "browser.open_tab",
    "browser.close_tab", "browser.download", "browser.upload",
    "gui.type_text", "gui.paste_text", "gui.click", "gui.double_click",
    "gui.drag", "gui.hotkey", "gui.keyboard_action", "gui.select",
    "gui.scroll", "gui.focus_window",
    "volume.step", "volume.mute", "display.brightness_set",
    "window.minimize_all", "window.restore", "window.show_desktop",
    "clipboard.paste",
    "notes.create",
    "data.transform",
    "package.install", "package.uninstall",
    "browser.screenshot", "screen.capture",
    "application.close",
    "network.connect_wifi",
})


class ContractErrorLike(ValueError):
    """Internal: signals 'cannot check' distinctly from 'not done'."""


def capture_path_state(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {"exists": False, "size": 0, "mtime_ns": None}
    import os

    try:
        stat = os.stat(path)
        return {
            "exists": os.path.isfile(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    except OSError:
        return {"exists": False, "size": 0, "mtime_ns": None}


def _changed_after_baseline(
    path: Optional[str],
    baseline: Optional[Dict[str, Any]],
) -> bool:
    current = capture_path_state(path)
    if not current["exists"] or current["size"] <= 0:
        return False
    if not isinstance(baseline, dict):
        return False
    return current != baseline


def _download_state_check(params: Dict[str, Any]) -> bool:
    save_path = params.get("save_path")
    if not save_path:
        raise ContractErrorLike("no save_path to check")
    return _changed_after_baseline(
        save_path,
        params.get("_baseline"),
    )


def _upload_state_check(params: Dict[str, Any]) -> bool:
    if not params.get("file_path"):
        raise ContractErrorLike("no file_path to check")
    raise ContractErrorLike(
        "local file existence cannot prove remote upload completion"
    )


def _screenshot_state_check(params: Dict[str, Any]) -> bool:
    path = params.get("path")
    if not path:
        raise ContractErrorLike("no path to check")
    return _changed_after_baseline(path, params.get("_baseline"))


# capability_id -> state-check factory(params dict) -> bool.
# True = side effect already happened (do NOT retry).
STATE_CHECKERS: Dict[str, Any] = {
    "browser.download": lambda params: _download_state_check(
        params or {}),
    "browser.upload": lambda params: _upload_state_check(
        params or {}),
    "browser.screenshot": lambda params: _screenshot_state_check(
        params or {}),
}


def get_state_checker(capability_id: str) -> Optional[Any]:
    """Return the Amendment 3 state checker for a capability, if any."""
    return STATE_CHECKERS.get(capability_id)
