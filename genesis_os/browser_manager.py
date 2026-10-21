"""Genesis OS — Browser Intelligence.
 
Provides generalized browser control capabilities.
 
Architecture:
    BrowserManager (high-level API)
          |
          +-- WebBrowserProvider (webbrowser-based, always available)
          +-- SeleniumProvider (optional, when installed)
          +-- PlaywrightProvider (optional, when installed)
 
Capabilities:
    - launch browser
    - navigate
    - search
    - inspect page
    - find text
    - click target
    - type
    - select
    - scroll
    - switch tab
    - open tab
    - close tab
    - download
    - upload
    - extract
    - verify page state
 
This module does NOT fake capabilities that are unavailable.
It reports limitations honestly.

Phase 5 — Per-operation provider resolution:

    Every public dispatch now re-resolves the provider from
    CapabilityProviderRegistry instead of using the session's
    cached provider.  A provider that becomes unhealthy
    mid-session is skipped for subsequent calls.  Each call
    is wrapped in an explicit timeout (Phase 5 Part 2);
    timeout counts as failure for fallback logic.
"""
from __future__ import annotations
 
import webbrowser
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus, urlparse
 
 
class BrowserProvider(ABC):
    """Abstract browser automation provider."""
 
    @property
    @abstractmethod
    def name(self) -> str:
        pass
 
    @property
    @abstractmethod
    def available(self) -> bool:
        pass
 
    @abstractmethod
    def open_url(self, url: str) -> Dict[str, Any]:
        pass
 
    @abstractmethod
    def navigate(self, url: str) -> Dict[str, Any]:
        pass
 
    @abstractmethod
    def search(self, query: str, engine: str = "google") -> Dict[str, Any]:
        pass
 
    # Advanced operations (may not be available)
    def click(self, selector: str) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.click", "error": f"{self.name} does not support click operations"}
 
    def type_text(self, selector: str, text: str) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.type", "error": f"{self.name} does not support type operations"}
 
    def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.scroll", "error": f"{self.name} does not support scroll operations"}
 
    def find_text(self, text: str) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.find", "error": f"{self.name} does not support find operations"}
 
    def extract_text(self, selector: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.extract", "error": f"{self.name} does not support extract operations"}
 
    def get_page_title(self) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.get_title", "error": f"{self.name} does not support get_title operations"}
 
    def get_page_url(self) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.get_url", "error": f"{self.name} does not support get_url operations"}
 
    def switch_tab(self, index: int) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.switch_tab", "error": f"{self.name} does not support tab operations"}
 
    def open_tab(self, url: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.open_tab", "error": f"{self.name} does not support tab operations"}
 
    def close_tab(self, index: Optional[int] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.close_tab", "error": f"{self.name} does not support tab operations"}
 
    def get_tabs(self) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.get_tabs", "error": f"{self.name} does not support tab operations"}
 
    def select(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.select", "error": f"{self.name} does not support select operations"}
 
    def download(self, url: str, save_path: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.download", "error": f"{self.name} does not support download operations"}
 
    def upload(self, selector: str, file_path: str) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.upload", "error": f"{self.name} does not support upload operations"}
 
    def wait_for_element(self, selector: str, timeout: float = 10.0) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.wait", "error": f"{self.name} does not support wait operations"}
 
    def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.screenshot", "error": f"{self.name} does not support screenshot operations"}

    def get_page_state(self) -> Dict[str, Any]:
        return {"success": False, "operation": "browser.get_page_state", "error": f"{self.name} does not support page state operations"}


class WebBrowserProvider(BrowserProvider):
    """Basic webbrowser-based provider (always available)."""
 
    name = "webbrowser"
    available = True
 
    @staticmethod
    def _safe_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False
 
    def open_url(self, url: str) -> Dict[str, Any]:
        url = str(url).strip()
        if not self._safe_url(url):
            return {"success": False, "operation": "browser.open_url", "error": "Only valid HTTP/HTTPS URLs are allowed."}
        try:
            opened = webbrowser.open(url)
            return {
                "success": bool(opened),
                "operation": "browser.open_url",
                "url": url,
                "executed": bool(opened),
                "verified": False,
                "verification_type": "browser_dispatch_only",
                "verification_reason": "webbrowser cannot read back the resulting page URL.",
            }
        except Exception as exc:
            return {"success": False, "operation": "browser.open_url", "error": str(exc)}
 
    def navigate(self, url: str) -> Dict[str, Any]:
        return self.open_url(url)
 
    def search(self, query: str, engine: str = "google") -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "operation": "browser.search", "error": "Search query is required."}
        domains = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q=",
            "youtube": "https://www.youtube.com/results?search_query=",
        }
        base = domains.get(str(engine).lower(), domains["google"])
        result = self.open_url(base + quote_plus(query.strip()))
        return {
            **result,
            "operation": "browser.search",
            "query": query.strip(),
            "engine": engine,
            "verified": False,
            "verification_type": "browser_dispatch_only",
            "verification_reason": "webbrowser cannot read back the resulting search page.",
        }
 
 
@dataclass
class BrowserSession:
    """Tracks browser session state."""
    provider: BrowserProvider
    tabs: List[Dict[str, Any]] = None
    current_tab_index: int = 0
 
    def __post_init__(self):
        if self.tabs is None:
            self.tabs = []
 
 
class BrowserManager:
    """High-level browser intelligence manager.
 
    Supports multiple providers and falls back gracefully.
    Phase 5: provider resolution happens per-operation via
    CapabilityProviderRegistry, not per-session.
    """
 
    VERSION = "5.0.0"

    # Default per-dispatch timeout in seconds.
    # A hung Playwright/Selenium call must not block Genesis
    # indefinitely.  Reuses the ThreadPoolExecutor pattern
    # from llm_intent_resolver.py (Phase 3).
    DEFAULT_DISPATCH_TIMEOUT: float = 30.0

    # Map operation names to registry capability IDs.
    # Operations not in this map fall back to session-based
    # resolution (backward compatible).
    _OPERATION_CAPABILITY_MAP: Dict[str, str] = {
        "click": "browser.click",
        "type_text": "browser.type",
        "scroll": "browser.scroll",
        "find_text": "browser.find",
        "extract_text": "browser.extract",
        "get_page_title": "browser.get_title",
        "get_page_url": "browser.get_url",
        "switch_tab": "browser.switch_tab",
        "open_tab": "browser.open_tab",
        "close_tab": "browser.close_tab",
        "get_tabs": "browser.get_tabs",
        "select": "browser.select",
        "download": "browser.download",
        "upload": "browser.upload",
        "screenshot": "browser.screenshot",
        "wait_for_element": "browser.wait",
        "get_page_state": "browser.get_page_state",
        "open_url": "browser.open_url",
        "navigate": "browser.open_url",
    }

    # Upper bound on the parallel provider probe performed in
    # __init__. A probe that cannot finish in this window is
    # abandoned rather than allowed to block construction.
    _PROVIDER_PROBE_TIMEOUT = 10.0
 
    def __init__(self):
        self._providers: List[BrowserProvider] = []
        self._sessions: Dict[str, BrowserSession] = {}
        self._default_session_id = "default"
        self._dispatch_lock = threading.Lock()

        # Item 21B (C33): True once the probe window has closed.
        # Probes started in this constructor may still be running
        # after that point (they are abandoned, not waited for); a
        # late answer is DISCARDED rather than applied to a manager
        # that already reported itself degraded. Read/written under
        # _dispatch_lock because the probe thread and this
        # constructor race for it.
        self._probe_window_closed = False

        # Why this manager is degraded, if it is. None means healthy.
        # Set below when an advanced provider is missing because its
        # probe did not finish, as opposed to being genuinely absent.
        self._degraded_reason: Optional[str] = None

        # Item 25C (C20): every registration attempt is classified and
        # recorded. failed = the registration code RAN and crashed
        # (name -> reason); absent = genuinely not installed or
        # reports itself unavailable (name -> reason). Before this
        # existed, `except Exception: pass` in the probe methods left
        # a crashed provider indistinguishable from one that was
        # never installed.
        self._provider_failures: Dict[str, str] = {}
        self._provider_absences: Dict[str, str] = {}
        # Why the PARALLEL probe path itself failed (None = it ran).
        self._probe_path_failure: Optional[str] = None

        # Always register the basic webbrowser provider
        self._providers.append(WebBrowserProvider())
        
        # Try to register advanced providers IN PARALLEL.
        # Each provider spawns a subprocess probe (~5s on Windows).
        # Running them concurrently cuts total wait from ~10s to ~5s.
        #
        # The wait is BOUNDED. Previously `wait([f_sel, f_pw])` had
        # no timeout, so a provider probe that blocks — Selenium's
        # constructor can reach the network via ChromeDriverManager —
        # held the constructor open indefinitely. MEASURED: under
        # CPU load this made
        # test_phase5_provider_registry::test_browser_manager_has_three_concrete_providers
        # fail intermittently, because neither advanced provider got
        # registered before the assertion ran. A timeout converts a
        # hang into a degraded-but-usable manager: webbrowser is
        # always present and the advanced providers appear on a
        # later construction once their probes warm.
        #
        # Item 21B (C33): that bounded `wait(..., timeout=...)` never
        # made the CONSTRUCTION bounded. The probes ran inside
        # `with ThreadPoolExecutor(...)`, future.cancel() cannot stop
        # a STARTED probe, and the `with` exit then ran
        # shutdown(wait=True) -- so the constructor still waited out
        # the full probe runtime. MEASURED on that original with
        # _PROVIDER_PROBE_TIMEOUT=1.0 and a probe sleeping 6s:
        # construction took 6.00s (and the 60s-stub degraded test
        # paid 60.40s).
        #
        # ThreadPoolExecutor + shutdown(wait=False) is NOT a fix
        # either: since Python 3.9 its workers are non-daemon
        # (bpo-39812) and threading._register_atexit(_python_exit)
        # joins every executor thread at interpreter exit regardless
        # of wait=. MEASURED: an 8s worker abandoned that way still
        # delayed interpreter exit by 8.19s. These probes are pure
        # diagnostics -- their only side effect is a provider-list
        # insert -- so they run as plain daemon threads with a
        # deadline join: construction returns at the bound, a
        # still-running probe is ABANDONED (a daemon thread cannot
        # block interpreter exit), and its late answer is discarded
        # via _probe_window_closed. "Did not answer within the
        # window" is exactly what degraded means; absent != failed
        # either way -- the reason below says TIMEOUT, never absence.
        try:
            import time as _time

            deadline = _time.monotonic() + self._PROVIDER_PROBE_TIMEOUT
            probes = (
                threading.Thread(
                    target=self._try_register_selenium,
                    name="browser_probe_selenium",
                    daemon=True,
                ),
                threading.Thread(
                    target=self._try_register_playwright,
                    name="browser_probe_playwright",
                    daemon=True,
                ),
            )
            for probe in probes:
                probe.start()
            for probe in probes:
                remaining = deadline - _time.monotonic()
                if remaining > 0.0:
                    probe.join(timeout=remaining)

            # Close the answer window and decide degraded from the
            # SAME snapshot, under the dispatch lock: a probe alive
            # here did not answer within the bound (degraded = a
            # TIMEOUT, not proof of absence -- the provider caches
            # retry after their TTL, so a LATER BrowserManager()
            # recovers), and any answer it produces after this point
            # is discarded by _register_provider.
            with self._dispatch_lock:
                self._probe_window_closed = True
                if any(p.is_alive() for p in probes):
                    # The probes are still running; they did not
                    # answer. This is what makes the manager
                    # degraded. Previously this state was silent,
                    # and the only evidence was a provider list
                    # missing its advanced entries.
                    self._degraded_reason = (
                        "provider probe timeout after "
                        f"{self._PROVIDER_PROBE_TIMEOUT}s")
        except Exception as exc:
            # Fallback: sequential if threading fails for any reason.
            # Item 25C (C20): record WHY the parallel path was lost --
            # this catch used to run the fallback and record nothing,
            # so the failure was invisible. Each provider's own
            # outcome is still recorded by _try_register_* below.
            self._try_register_selenium()
            self._try_register_playwright()
            with self._dispatch_lock:
                self._probe_window_closed = True
                self._probe_path_failure = (
                    "parallel probe path failed: "
                    f"{type(exc).__name__}: {exc} "
                    "(sequential fallback used)"
                )
        
        # Initialize default session
        self._ensure_session(self._default_session_id)

        # Phase 5: lazy-init the capability provider registry
        self._registry = None

    @property
    def degraded(self) -> bool:
        """True when an advanced provider is missing because its probe
        timed out, not because it is genuinely unavailable.

        Observable on purpose. Before this existed, a degraded manager
        was indistinguishable from a machine with no browser drivers,
        and the only symptom was an assertion elsewhere noticing a
        short provider list.
        """
        return self._degraded_reason is not None

    @property
    def degraded_reason(self) -> Optional[str]:
        return self._degraded_reason

    @property
    def provider_failures(self) -> Dict[str, str]:
        """name -> reason for providers whose registration CRASHED.

        Item 25C (C20): a crash is not absence. An entry here means
        the registration code RAN and failed -- exposed so a dead
        provider never masquerades as one that was never installed.
        """
        with self._dispatch_lock:
            return dict(self._provider_failures)

    @property
    def provider_absences(self) -> Dict[str, str]:
        """name -> reason for providers that are genuinely not
        installed or report themselves unavailable."""
        with self._dispatch_lock:
            return dict(self._provider_absences)

    @property
    def probe_path_failure(self) -> Optional[str]:
        """Why the parallel probe path itself failed (None = it ran)."""
        with self._dispatch_lock:
            return self._probe_path_failure

    def _record_provider_failure(self, name: str, reason: str) -> None:
        """Item 25C (C20): note that a provider's registration crashed."""
        with self._dispatch_lock:
            self._provider_failures[name] = reason

    def _record_provider_absence(self, name: str, reason: str) -> None:
        """Item 25C (C20): note that a provider is genuinely not
        installed/available -- distinct from a crash."""
        with self._dispatch_lock:
            self._provider_absences[name] = reason

    @property
    def provider_names(self) -> List[str]:
        """Names of the registered providers, in dispatch preference order."""
        return [p.name for p in self._providers]

    def _get_registry(self):
        """Lazy-init the capability provider registry."""
        if self._registry is None:
            try:
                from .capability_provider_registry import (
                    CapabilityProviderRegistry,
                )
                self._registry = CapabilityProviderRegistry()
            except Exception:
                self._registry = False  # Sentinel: import failed
        return self._registry if self._registry is not False else None
 
    def _register_provider(self, provider: BrowserProvider) -> None:
        """Add a probe-answered provider while the window is open.

        A probe that finishes after the constructor's probe window
        closed has its answer DISCARDED: it did not answer within the
        bound, and the constructor already reported this manager
        degraded ("advanced provider missing because its probe timed
        out"). Applying it late would make that flag a lie -- the
        provider belongs to a LATER BrowserManager() once the probe
        cache warms, not to this one. The insert runs under
        _dispatch_lock so it cannot race a dispatch iterating
        _providers either.
        """
        with self._dispatch_lock:
            if self._probe_window_closed:
                return
            self._providers.insert(0, provider)

    def _try_register_selenium(self) -> None:
        """Try to register Selenium provider if available.

        Item 25C (C20): every outcome is RECORDED. The old
        ``except ImportError: pass`` / ``except Exception: pass``
        swallowed a crash without a trace -- a provider that CRASHED
        looked identical to one that was never installed. Now:
        ImportError -> absent (reason recorded), available False ->
        absent (reason recorded), any other exception -> failed
        (reason recorded).
        """
        name = "selenium"
        try:
            from .browser_selenium import SeleniumBrowserProvider
        except ImportError as exc:
            self._record_provider_absence(name, f"ImportError: {exc}")
            return
        try:
            provider = SeleniumBrowserProvider()
            if not provider.available:
                self._record_provider_absence(
                    name, "installed but provider.available is False"
                )
                return
            self._register_provider(provider)
        except Exception as exc:
            self._record_provider_failure(
                name, f"{type(exc).__name__}: {exc}"
            )

    def _try_register_playwright(self) -> None:
        """Try to register Playwright provider if available.

        Item 25C (C20): same contract as _try_register_selenium --
        ImportError/available-False -> absent with reason, any other
        exception -> failed with reason; nothing is silently dropped.
        """
        name = "playwright"
        try:
            from .browser_playwright import PlaywrightBrowserProvider
        except ImportError as exc:
            self._record_provider_absence(name, f"ImportError: {exc}")
            return
        try:
            provider = PlaywrightBrowserProvider()
            if not provider.available:
                self._record_provider_absence(
                    name, "installed but provider.available is False"
                )
                return
            self._register_provider(provider)
        except Exception as exc:
            self._record_provider_failure(
                name, f"{type(exc).__name__}: {exc}"
            )
 
    def _get_provider(self) -> BrowserProvider:
        """Get the best available provider (session-level fallback)."""
        for provider in self._providers:
            if provider.available:
                return provider
        return self._providers[0]  # Fallback to basic
 
    def _ensure_session(self, session_id: str) -> BrowserSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = BrowserSession(provider=self._get_provider())
        return self._sessions[session_id]
 
    def _get_session(self, session_id: str = "default") -> BrowserSession:
        return self._ensure_session(session_id)

    # =========================================================
    # PHASE 5: PER-OPERATION DISPATCH WITH FALLBACK
    # =========================================================

    def _resolve_provider_for_operation(
        self,
        operation: str,
        session_id: str = "default",
    ) -> Optional[BrowserProvider]:
        """Resolve the best provider for a specific operation.

        Uses CapabilityProviderRegistry when available, falling
        back to session-based resolution for backward compat.
        """
        registry = self._get_registry()
        capability_id = self._OPERATION_CAPABILITY_MAP.get(operation)

        if registry and capability_id:
            entry = registry.get_healthy_provider(capability_id)
            if entry:
                # Find the matching BrowserProvider instance
                for provider in self._providers:
                    if (
                        provider.name == entry.provider_name
                        and provider.available
                    ):
                        return provider

        # Fallback: session-based (original behavior)
        session = self._get_session(session_id)
        return session.provider

    # Providers whose driver objects are bound to the creating thread
    # (Playwright sync API greenlets / Selenium driver sessions) must
    # NOT be dispatched via ThreadPoolExecutor — greenlets cannot
    # switch threads.  These run in-process on the calling thread.
    _THREAD_UNSAFE_PROVIDER_NAMES = frozenset({
        "playwright",
        "PlaywrightBrowserProvider",
        "selenium",
        "SeleniumBrowserProvider",
    })

    @classmethod
    def _is_thread_unsafe(cls, provider_name: Optional[str]) -> bool:
        """Return True if provider must run on the calling thread.

        Matches exact provider names and substring matches
        (e.g. mock wrappers named 'mock_playwright') so wrapped
        thread-unsafe providers are also dispatched in-process.
        """
        if not provider_name:
            return False
        name_lower = str(provider_name).lower()
        for unsafe in cls._THREAD_UNSAFE_PROVIDER_NAMES:
            if name_lower == unsafe.lower() or unsafe.lower() in name_lower:
                return True
        return False

    def _dispatch_with_timeout(
        self,
        fn: Callable,
        timeout: float,
        provider_name: Optional[str] = None,
    ) -> Any:
        """Run fn() with an explicit timeout.

        Phase 5 Part 2: A hung provider call must not block
        Genesis indefinitely.  Timeout raises FuturesTimeoutError.
        Reuses the ThreadPoolExecutor pattern from
        llm_intent_resolver.py (Phase 3).

        Greenlet/thread-affinity fix: Playwright sync API (greenlet)
        and Selenium driver sessions are bound to the creating
        thread and CANNOT be dispatched to a worker thread
        ("greenlet.error: cannot switch to a different thread").
        Thread-unsafe providers run IN-PROCESS on the calling
        thread via a direct fn() call.  Timeout for these is
        best-effort only — no hard kill is possible without a
        thread switch, so we call directly and record latency
        instead of enforcing a hard timeout.

        For thread-safe providers, a timed-out call is ABANDONED,
        not killed: the worker thread running fn() cannot be
        interrupted, so it keeps running (holding whatever it
        holds) until fn() returns on its own. What this method
        guarantees is only that the CALLER stops waiting at the
        timeout — never that the provider call was stopped.
        """
        # If provider_name not given explicitly, try to recover it
        # from the closure/defaults of the dispatch lambda
        # (``lambda p=provider: fn(p)`` carries the provider).
        if provider_name is None:
            try:
                defaults = getattr(fn, "__defaults__", None) or ()
                for candidate in defaults:
                    cname = getattr(candidate, "name", None)
                    if isinstance(cname, str) and self._is_thread_unsafe(cname):
                        provider_name = cname
                        break
                else:
                    closure = getattr(fn, "__closure__", None) or ()
                    for cell in closure:
                        try:
                            candidate = cell.cell_contents
                        except ValueError:
                            continue
                        cname = getattr(candidate, "name", None)
                        if isinstance(cname, str) and self._is_thread_unsafe(cname):
                            provider_name = cname
                            break
            except Exception:
                provider_name = None

        if self._is_thread_unsafe(provider_name):
            import time as _time
            start = _time.monotonic()
            result = None
            try:
                # Item 13B (C5): there is deliberately NO pre-call
                # deadline check here any more.
                #
                # The previous
                #
                #     if _time.monotonic() - start > timeout:
                #         raise FuturesTimeoutError(timeout)
                #
                # ran BEFORE `fn()`, so `start` was microseconds old and
                # the condition was never true. It looked like a hard
                # timeout and enforced nothing.
                #
                # Real enforcement is now where it can actually bite:
                # the providers set driver-level timeouts at creation
                # (Playwright set_default_timeout /
                # set_default_navigation_timeout and an explicit goto
                # timeout; Selenium page-load and script timeouts, and a
                # bounded ChromeDriverManager download). A driver that
                # respects those raises on its own.
                result = fn()
            finally:
                elapsed = _time.monotonic() - start
                if isinstance(result, dict):
                    try:
                        result.setdefault("_dispatch_latency_s", round(elapsed, 3))
                        result.setdefault("_dispatch_mode", "in_process")
                    except Exception:
                        pass
            # Item 13B (C5): an overrun now FAILS the operation.
            #
            # It used to set `_timeout_overrun` and return the result
            # unchanged, so a call that blew its deadline by 10x was
            # handed back as success=True to any caller that trusted the
            # flag. The overrun flag is kept, because it is honest
            # information, but it no longer rides on a success.
            #
            # What we still cannot do is KILL the call: the provider is
            # running on this thread because Playwright and Selenium are
            # bound to their creating thread. So this is not a hard
            # timeout and is not described as one -- it is a refusal to
            # certify a result we know missed its deadline. The driver
            # level timeouts are what bound the wall clock; this is what
            # stops a late result being reported as a good one.
            if isinstance(result, dict) and elapsed > timeout:
                result.setdefault("_timeout_overrun", True)
                result.setdefault("_timeout_s", timeout)
                result["success"] = False
                result["verified"] = False
                result["error"] = (
                    f"{provider_name or 'provider'} call took "
                    f"{round(elapsed, 3)}s against a {timeout}s budget. "
                    f"The driver could not be interrupted mid-call, so "
                    f"this operation is reported as FAILED rather than "
                    f"successful-but-late."
                )
                result.setdefault("operation", "browser.dispatch")
                result.setdefault("executed", False)
            return result

        # Item 17A (C14): this used to be
        #
        #     with ThreadPoolExecutor(max_workers=1) as executor:
        #         future = executor.submit(fn)
        #         return future.result(timeout=timeout)
        #
        # The `with` form made the timeout unenforceable. future.result
        # DID raise FuturesTimeoutError at `timeout`, but the block then
        # ran ThreadPoolExecutor.__exit__ -> shutdown(wait=True), which
        # waits for the hung fn() to finish. Measured: a 2.0s sleep
        # against a 0.3s budget returned at 2.000s. The timeout fired
        # on paper and cost the caller the entire overrun.
        #
        # The executor is now built explicitly, and on timeout we
        # shutdown(wait=False, cancel_futures=True) so the CALL returns
        # promptly -- mirroring llm_intent_resolver.py and
        # browser_selenium.py's driver download.
        #
        # THE HONEST LIMIT, stated rather than hidden: wait=False does
        # not kill anything. The worker thread running fn() cannot be
        # interrupted, so on timeout it is ABANDONED -- still running,
        # still holding whatever it holds (driver sessions, sockets),
        # until fn() returns on its own. Nothing here claims the
        # provider call was stopped; only that the CALLER is no longer
        # blocked behind it. Thread-unsafe providers still take the
        # in-process path above and are unaffected by this change.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(fn)
            result = future.result(timeout=timeout)
        except FuturesTimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            # NOTE: the `return` is deliberately OUTSIDE the try block.
            # A return inside `try` skips the `else` clause entirely
            # (verified: try/else with return in try never reaches
            # else), which would leave the worker thread un-joined on
            # the success path -- a thread leak on every healthy call.
            executor.shutdown(wait=True)
            return result

    def _dispatch_with_fallback(
        self,
        operation: str,
        fn: Callable,
        session_id: str = "default",
        timeout: Optional[float] = None,
        state_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Dispatch an operation with per-operation provider resolution,
        explicit timeout, and provider fallback.

        Phase 5 acceptance gate: provider resolution happens on
        EVERY operation, not just at session start.  A provider
        that becomes unhealthy mid-session is skipped.

        Amendment 3: when the capability is NON-idempotent and a
        provider fails or times out, a real state check runs
        BEFORE the next provider is attempted.  If the side effect
        already happened, success is reported without retrying.
        If no state checker exists, fallback is refused rather
        than retried blind (fail-closed).

        THE DISPATCH LOCK GUARDS SHARED STATE ONLY; it does NOT
        wrap the blocking provider call (Item 17B / C15).
        It used to wrap this entire function, so one slow
        operation blocked every independent operation on the
        instance for its whole duration (reproduced: a fast call
        waited 0.844s behind an unrelated 1.0s sleep).
        Locked (fast, no blocking work inside):
          - provider-chain resolution (reads self._providers and
            the lazy init in _get_registry)
          - session lookup/creation (mutates self._sessions)
          - registry health writes on timeout/failure, each
            wrapped individually around the write
        NOT locked, and why that is safe:
          - the provider call: driver mutual exclusion is the
            PROVIDER's job and is already done per method behind
            the provider's own lock -- browser_playwright wraps
            every method in `with self._lock`, and
            browser_selenium documents that "every provider
            method is already serialised behind self._lock"
          - _amendment3_gate: it runs the caller's state_check
            callback, which is user code and may itself block
          - liveness probes (_is_browser_alive): driver reads,
            protected by the same provider lock
        Residual, stated honestly: two dispatches that both name
        a thread-SAFE provider can now run concurrently (before,
        this lock serialized them). Thread-unsafe providers
        (playwright/selenium) were never made cross-thread-safe
        by this lock: their thread affinity rejects a foreign
        thread whether or not the lock is held.
        """
        with self._dispatch_lock:
            if timeout is None:
                timeout = self.DEFAULT_DISPATCH_TIMEOUT

            registry = self._get_registry()
            capability_id = self._OPERATION_CAPABILITY_MAP.get(operation)
            is_idempotent = False
            if registry and capability_id:
                is_idempotent = registry.is_idempotent(capability_id)

            # Build the provider chain to try
            providers_to_try: List[BrowserProvider] = []

            if registry and capability_id:
                for entry in registry.get_provider_chain(capability_id):
                    for provider in self._providers:
                        if (
                            provider.name == entry.provider_name
                            and provider.available
                        ):
                            providers_to_try.append(provider)
                            break

            if not providers_to_try:
                # No registry coverage — use session provider
                session = self._get_session(session_id)
                providers_to_try = [session.provider]

        # ITEM 17B (C15): the critical section ends above.
        # Everything below can block -- the provider call itself,
        # the Amendment-3 state check (caller callback) and the
        # liveness probes -- and running it under this lock made
        # one slow operation block every independent operation on
        # the instance (reproduced: 0.844s for an unrelated fast
        # call behind a 1.0s sleep). Shared-state mutation only:
        # chain/session resolution above, registry health writes
        # below, each wrapped in this lock individually.
        last_error = None
        for provider in providers_to_try:
            if not getattr(provider, "available", False):
                continue
            if (
                getattr(provider, "name", "") == "playwright"
                and getattr(provider, "_browser", None) is not None
            ):
                try:
                    if not provider._is_browser_alive():
                        continue
                except Exception:
                    continue
            try:
                result = self._dispatch_with_timeout(
                    lambda p=provider: fn(p),
                    timeout,
                    provider_name=provider.name,
                )
                if isinstance(result, dict):
                    result.setdefault("_provider", provider.name)
                    if result.get("error") and result.get("success") is True:
                        result["success"] = False
                        result["verified"] = False
                        result["status"] = "execution_failed"
                    if result.get("success") is False:
                        last_error = str(
                            result.get("error")
                            or result.get("message")
                            or f"{provider.name} reported failure"
                        )
                        refusal = self._amendment3_gate(
                            operation,
                            capability_id,
                            is_idempotent,
                            provider.name,
                            last_error,
                            state_check,
                        )
                        if refusal is not None:
                            return refusal
                        continue
                return result
            except FuturesTimeoutError:
                last_error = f"{provider.name} timed out after {timeout}s"
                with self._dispatch_lock:
                    if registry and capability_id:
                        for entry in registry.get_provider_chain(capability_id):
                            if entry.provider_name == provider.name:
                                entry.last_health_check_result = False
                                entry.last_health_check_time = __import__("time").monotonic()
                refusal = self._amendment3_gate(
                    operation, capability_id, is_idempotent,
                    provider.name, last_error, state_check)
                if refusal is not None:
                    return refusal
                continue
            except Exception as exc:
                last_error = f"{provider.name} failed: {exc}"
                with self._dispatch_lock:
                    if registry and capability_id:
                        for entry in registry.get_provider_chain(capability_id):
                            if entry.provider_name == provider.name:
                                entry.last_health_check_result = False
                                entry.last_health_check_time = __import__("time").monotonic()
                refusal = self._amendment3_gate(
                    operation, capability_id, is_idempotent,
                    provider.name, last_error, state_check)
                if refusal is not None:
                    return refusal
                continue

        # All providers failed
        return {
            "success": False,
            "operation": operation,
            "error": f"All providers failed. Last error: {last_error}",
            "_provider": (
                providers_to_try[-1].name
                if providers_to_try
                else "none"
            ),
            "_providers": [
                provider.name for provider in providers_to_try
            ],
        }

    @staticmethod
    def _amendment3_gate(
        operation: str,
        capability_id: Optional[str],
        is_idempotent: bool,
        provider_name: str,
        last_error: str,
        state_check: Optional[Callable[[], bool]],
    ) -> Optional[Dict[str, Any]]:
        """Amendment 3 enforcement. Returns a result dict to stop
        fallback, or None to allow trying the next provider.

        - Idempotent: blind retry allowed (None).
        - Non-idempotent + state check says completed: report
          success WITHOUT retrying (the side effect happened).
        - Non-idempotent + state check says absent: allow fallback,
          annotated with the check outcome.
        - Non-idempotent + no checker: fail closed (refuse blind
          retry) rather than risk duplicate side effects.
        """
        if is_idempotent:
            return None
        if state_check is None:
            return {
                "success": False,
                "operation": operation,
                "capability": capability_id,
                "error": (
                    f"Non-idempotent '{capability_id}' failed on "
                    f"{provider_name} ({last_error}) with no state "
                    "checker available; refusing blind fallback."
                ),
                "fallback_refused": True,
                "_provider": provider_name,
            }
        try:
            completed = bool(state_check())
        except Exception as exc:
            return {
                "success": False,
                "operation": operation,
                "capability": capability_id,
                "error": (
                    f"Non-idempotent '{capability_id}' failed on "
                    f"{provider_name} ({last_error}) and its state "
                    f"check errored ({exc}); refusing blind fallback."
                ),
                "fallback_refused": True,
                "_provider": provider_name,
            }
        if completed:
            return {
                "success": True,
                "operation": operation,
                "capability": capability_id,
                "completed_despite_failure": True,
                "state_check_passed": True,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "post_dispatch_state_check",
                "message": (
                    f"'{capability_id}' failed on {provider_name} "
                    f"({last_error}) but the side effect already "
                    "happened; not retried."
                ),
                "_provider": provider_name,
            }
        return None
 
    # =========================================================
    # PUBLIC API — Phase 5: per-operation dispatch with fallback
    # =========================================================
 
    def open_url(self, url: str, session_id: str = "default") -> Dict[str, Any]:
        """Open a URL in the browser."""
        return self._dispatch_with_fallback(
            "open_url",
            lambda p: p.open_url(url),
            session_id,
        )
 
    def navigate(self, url: str, session_id: str = "default") -> Dict[str, Any]:
        """Navigate to a URL."""
        return self._dispatch_with_fallback(
            "navigate",
            lambda p: p.navigate(url),
            session_id,
        )
 
    def search(self, query: str, engine: str = "google", session_id: str = "default") -> Dict[str, Any]:
        """Search the web."""
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "operation": "browser.search", "error": "Search query is required."}
        # Item 13A (C4): the `if "open_url" in self.__dict__` branch that
        # used to sit here is DELETED, not repaired.
        #
        # It was unreachable on every instance. `self.__dict__` holds
        # INSTANCE attributes; `open_url` is a method on the class, so it
        # can never appear there. The guard was therefore always False
        # and the dispatch below always ran.
        #
        # It was also testing the wrong thing twice over. The capability
        # it wanted -- "can this manager open a URL?" -- is ALWAYS true,
        # since open_url is defined right here, so a capability check
        # would have been pointless. And what the condition actually
        # responded to was the presence of an unrelated instance
        # attribute: setting a stray `mgr.open_url = something` was
        # enough to flip it on, with no bearing on whether any browser
        # existed.
        #
        # Deleting rather than repairing is safe because the branch was a
        # FOURTH copy of search logic. Every provider already owns one:
        #   WebBrowserProvider.search()    (this file, line ~166)
        #   PlaywrightBrowserProvider.search()  (browser_playwright.py:301)
        #   SeleniumBrowserProvider.search()   (browser_selenium.py:189)
        # Each builds its engine URL with the same domain table the dead
        # branch did. The branch also bypassed _dispatch_with_fallback,
        # so had it ever run it would have SKIPPED provider selection and
        # provider fallback -- strictly worse than the path that is
        # actually taken.
        result = self._dispatch_with_fallback(
            "search",
            lambda p: p.search(query, engine),
            session_id,
        )
        if isinstance(result, dict):
            result.setdefault("query", query.strip())
            result.setdefault("engine", engine)
        return result
 
    # --- Advanced operations (dispatch with fallback) ---
 
    def click(self, selector: str, session_id: str = "default") -> Dict[str, Any]:
        """Click an element by CSS selector."""
        return self._dispatch_with_fallback(
            "click",
            lambda p: p.click(selector),
            session_id,
        )
 
    def type_text(self, selector: str, text: str, session_id: str = "default") -> Dict[str, Any]:
        """Type text into an element."""
        return self._dispatch_with_fallback(
            "type_text",
            lambda p: p.type_text(selector, text),
            session_id,
        )
 
    def scroll(self, direction: str = "down", amount: int = 3, session_id: str = "default") -> Dict[str, Any]:
        """Scroll the page."""
        return self._dispatch_with_fallback(
            "scroll",
            lambda p: p.scroll(direction, amount),
            session_id,
        )
 
    def find_text(self, text: str, session_id: str = "default") -> Dict[str, Any]:
        """Find text on the page."""
        return self._dispatch_with_fallback(
            "find_text",
            lambda p: p.find_text(text),
            session_id,
        )
 
    def extract_text(self, selector: Optional[str] = None, session_id: str = "default") -> Dict[str, Any]:
        """Extract text from the page."""
        return self._dispatch_with_fallback(
            "extract_text",
            lambda p: p.extract_text(selector),
            session_id,
        )
 
    def get_page_title(self, session_id: str = "default") -> Dict[str, Any]:
        """Get the current page title."""
        return self._dispatch_with_fallback(
            "get_page_title",
            lambda p: p.get_page_title(),
            session_id,
        )
 
    def get_page_url(self, session_id: str = "default") -> Dict[str, Any]:
        """Get the current page URL."""
        return self._dispatch_with_fallback(
            "get_page_url",
            lambda p: p.get_page_url(),
            session_id,
        )
 
    def switch_tab(self, index: int, session_id: str = "default") -> Dict[str, Any]:
        """Switch to a tab by index."""
        return self._dispatch_with_fallback(
            "switch_tab",
            lambda p: p.switch_tab(index),
            session_id,
        )
 
    def open_tab(self, url: Optional[str] = None, session_id: str = "default") -> Dict[str, Any]:
        """Open a new tab."""
        return self._dispatch_with_fallback(
            "open_tab",
            lambda p: p.open_tab(url),
            session_id,
        )
 
    def close_tab(self, index: Optional[int] = None, session_id: str = "default") -> Dict[str, Any]:
        """Close a tab."""
        return self._dispatch_with_fallback(
            "close_tab",
            lambda p: p.close_tab(index),
            session_id,
        )
 
    def get_tabs(self, session_id: str = "default") -> Dict[str, Any]:
        """Get list of open tabs."""
        return self._dispatch_with_fallback(
            "get_tabs",
            lambda p: p.get_tabs(),
            session_id,
        )
 
    def wait_for_element(self, selector: str, timeout: float = 10.0, session_id: str = "default") -> Dict[str, Any]:
        """Wait for an element to appear."""
        return self._dispatch_with_fallback(
            "wait_for_element",
            lambda p: p.wait_for_element(selector, timeout),
            session_id,
        )
  
    def select(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None, session_id: str = "default") -> Dict[str, Any]:
        """Select an option from a dropdown/select element."""
        return self._dispatch_with_fallback(
            "select",
            lambda p: p.select(selector, value=value, label=label, index=index),
            session_id,
        )
  
    def download(self, url: str, save_path: Optional[str] = None, session_id: str = "default") -> Dict[str, Any]:
        """Download a file from a URL."""
        state_check = None
        if save_path:
            try:
                from .capability_provider_registry import (
                    capture_path_state,
                    get_state_checker,
                )
                factory = get_state_checker("browser.download")
                if factory is not None:
                    params = {
                        "save_path": save_path,
                        "_baseline": capture_path_state(save_path),
                    }
                    state_check = lambda: factory(params)  # noqa: E731
            except Exception:
                state_check = None
        return self._dispatch_with_fallback(
            "download",
            lambda p: p.download(url, save_path),
            session_id,
            state_check=state_check,
        )
  
    def upload(self, selector: str, file_path: str, session_id: str = "default") -> Dict[str, Any]:
        """Upload a file to a file input element."""
        state_check = None
        if file_path:
            try:
                from .capability_provider_registry import get_state_checker
                factory = get_state_checker("browser.upload")
                if factory is not None:
                    params = {"file_path": file_path}
                    state_check = lambda: factory(params)  # noqa: E731
            except Exception:
                state_check = None
        return self._dispatch_with_fallback(
            "upload",
            lambda p: p.upload(selector, file_path),
            session_id,
            state_check=state_check,
        )

    def screenshot(self, path: Optional[str] = None, session_id: str = "default") -> Dict[str, Any]:
        """Take a screenshot of the current page."""
        state_check = None
        if path:
            try:
                from .capability_provider_registry import (
                    capture_path_state,
                    get_state_checker,
                )
                factory = get_state_checker("browser.screenshot")
                if factory is not None:
                    params = {
                        "path": path,
                        "_baseline": capture_path_state(path),
                    }
                    state_check = lambda: factory(params)  # noqa: E731
            except Exception:
                state_check = None
        return self._dispatch_with_fallback(
            "screenshot",
            lambda p: p.screenshot(path),
            session_id,
            state_check=state_check,
        )

    def get_page_state(self, session_id: str = "default") -> Dict[str, Any]:
        """Phase 8: Capture full browser page state for observation."""
        return self._dispatch_with_fallback(
            "get_page_state",
            lambda p: p.get_page_state(),
            session_id,
        )

    def verify_page_state(self, expected_url: Optional[str] = None, expected_title_contains: Optional[str] = None, session_id: str = "default") -> Dict[str, Any]:
        """Verify the current page state matches expectations.

        This is a composite operation that checks URL and/or title
        against the current provider's reported state.  It does NOT
        dispatch to a provider-level ``verify_page_state`` (which does
        not exist on any provider); instead it reads the page URL and
        title from the provider and compares locally.
        """
        provider = self._resolve_provider_for_operation("get_page_url", session_id)
        checks: List[Dict[str, Any]] = []
        all_passed = True

        if expected_url is not None:
            url_result = self.get_page_url(session_id)
            actual_url = url_result.get("url", "") if isinstance(url_result, dict) else ""
            passed = actual_url == expected_url
            if not passed:
                all_passed = False
            checks.append({
                "type": "url",
                "passed": passed,
                "expected": expected_url,
                "actual": actual_url,
            })

        if expected_title_contains is not None:
            title_result = self.get_page_title(session_id)
            actual_title = title_result.get("title", "") if isinstance(title_result, dict) else ""
            passed = expected_title_contains.lower() in actual_title.lower()
            if not passed:
                all_passed = False
            checks.append({
                "type": "title",
                "passed": passed,
                "expected": expected_title_contains,
                "actual": actual_title,
            })

        return {"success": all_passed, "operation": "browser.verify_page_state", "checks": checks}
 
    def get_available_capabilities(self) -> Dict[str, bool]:
        """Report which capabilities are available with the current provider."""
        provider = self._get_provider()
        return {
            "provider": provider.name,
            "open_url": True,
            "navigate": True,
            "search": True,
            "click": hasattr(provider, 'click') and provider.available and provider.name != "webbrowser",
            "type_text": hasattr(provider, 'type_text') and provider.available and provider.name != "webbrowser",
            "scroll": hasattr(provider, 'scroll') and provider.available and provider.name != "webbrowser",
            "find_text": hasattr(provider, 'find_text') and provider.available and provider.name != "webbrowser",
            "extract_text": hasattr(provider, 'extract_text') and provider.available and provider.name != "webbrowser",
            "get_page_title": hasattr(provider, 'get_page_title') and provider.available and provider.name != "webbrowser",
            "get_page_url": hasattr(provider, 'get_page_url') and provider.available and provider.name != "webbrowser",
            "tab_management": hasattr(provider, 'switch_tab') and provider.available and provider.name != "webbrowser",
            "wait_for_element": hasattr(provider, 'wait_for_element') and provider.available and provider.name != "webbrowser",
            "screenshot": hasattr(provider, 'screenshot') and provider.available and provider.name != "webbrowser",
            "verify_page_state": True,
        }

    def close(self) -> Dict[str, Any]:
        errors = []
        seen = set()
        for provider in self._providers:
            identity = id(provider)
            if identity in seen:
                continue
            seen.add(identity)
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    errors.append(
                        f"{getattr(provider, 'name', 'provider')}: {exc}"
                    )
        self._sessions.clear()
        return {
            "success": not errors,
            "operation": "browser.close",
            "errors": errors,
        }