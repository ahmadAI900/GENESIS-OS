"""Genesis OS — Playwright Browser Provider.

Optional provider for advanced browser automation using Playwright.
Only loads if playwright is installed AND the browser binaries
have been downloaded via ``playwright install``. The provider
defaults to headless mode so a missing display does not break
search()-style calls; opt in to a visible browser with the
``GENESIS_BROWSER_HEADLESS=false`` environment variable.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from .browser_manager import BrowserProvider

# Module-level cache: probe result computed once, reused by all
# PlaywrightBrowserProvider instances.  On Windows the subprocess
# spawn + reimport takes ~5s per probe, so caching avoids the
# cost on every BrowserManager() instantiation.
_probe_cache: int = -1  # -1 = not yet probed

# A TIMEOUT IS NOT AN ANSWER.
#
# The probe spawns a child process and joins it with a 5s bound. If the
# machine is busy, that bound is hit and the probe says nothing about
# whether chromium is installed. Caching that as "unavailable" made the
# provider unrecoverable for the life of the process -- the original
# failure signature being `provider_names == ['webbrowser']`.
#
# So the cache records WHY a result was produced:
#   "definitive"  the probe finished and answered. Cache forever.
#   "timeout"     the probe did not answer. Cache only for the TTL,
#                 then re-probe.
_PROBE_CACHE_TTL_SECONDS = 60.0
_probe_cache_kind: str = ""      # "" | "definitive" | "timeout"
_probe_cache_at: float = 0.0     # monotonic, when the result was stored


def _probe_cache_is_valid() -> bool:
    """Is the cached probe result still usable?"""
    if _probe_cache < 0:
        return False
    if _probe_cache_kind == "timeout":
        return (time.monotonic() - _probe_cache_at) < _PROBE_CACHE_TTL_SECONDS
    return True


def _store_probe_result(value: int, kind: str) -> None:
    global _probe_cache, _probe_cache_kind, _probe_cache_at
    _probe_cache = value
    _probe_cache_kind = kind
    _probe_cache_at = time.monotonic()


def _probe_chromium_subprocess(result_ref):
    """Target function for multiprocessing Playwright Chromium probe.

    Must be defined at module level (not nested) so it can be
    pickled on Windows where multiprocessing uses 'spawn'.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path:
                result_ref.value = 1 if os.path.isfile(path) else 0
            else:
                result_ref.value = 0
    except Exception:
        result_ref.value = 0


class PlaywrightBrowserProvider(BrowserProvider):
    """Playwright-based browser automation provider."""

    name = "playwright"

    # Item 13B (C5): real driver-level timeouts.
    #
    # The manager cannot interrupt a Playwright call -- the sync API is
    # bound to the thread that created it, which is exactly why this
    # provider is treated as thread-unsafe and dispatched in-process. So
    # the wall clock has to be bounded HERE, by the driver, instead of by
    # a wrapper that hopes to give up.
    #
    # These are genuine Playwright timeouts: `launch` bounds browser
    # startup, and set_default_timeout / set_default_navigation_timeout
    # make every subsequent action and navigation give up on its own.
    # A driver that respects them raises TimeoutError, which the manager
    # sees as a provider error rather than a silent hang.
    LAUNCH_TIMEOUT_MS = 30_000
    DEFAULT_TIMEOUT_MS = 15_000
    NAVIGATION_TIMEOUT_MS = 30_000

    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._lock = threading.RLock()
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        """Verify the ``playwright`` Python package imports AND a
        chromium browser binary is installed.

        Uses a module-level cache so the expensive subprocess
        probe runs at most once per process, not per instance --
        unless the probe TIMED OUT, which is re-tried after the TTL.
        """
        if _probe_cache_is_valid():
            return bool(_probe_cache)
        try:
            import playwright  # noqa: F401
        except ImportError:
            _store_probe_result(0, "definitive")
            return False
        import multiprocessing as _mp
        result = _mp.Value("i", 0)
        proc = _mp.Process(target=_probe_chromium_subprocess, args=(result,))
        proc.start()
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            # Not a definitive "chromium is absent" -- the probe simply
            # did not answer in time. Retry after the TTL.
            _store_probe_result(0, "timeout")
            return False
        _store_probe_result(1 if result.value else 0, "definitive")
        if not _probe_cache:
            from pathlib import Path
            roots = []
            configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
            if configured and configured != "0":
                roots.append(Path(configured))
            local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
            if local_app_data:
                roots.append(Path(local_app_data) / "ms-playwright")
            roots.append(Path.home() / "AppData" / "Local" / "ms-playwright")
            for root in roots:
                try:
                    if any(root.glob("chromium-*/chrome-win*/chrome.exe")):
                        _store_probe_result(1, "definitive")
                        break
                except OSError:
                    continue
        return bool(_probe_cache)

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _resolve_headless() -> bool:
        """Default to headless; allow ``GENESIS_BROWSER_HEADLESS=false``
        to opt in to a visible browser for development."""
        raw = os.environ.get("GENESIS_BROWSER_HEADLESS")
        if raw is None:
            return True
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    def _ensure_browser(self):
        """Ensure browser is initialized.

        On launch failure, mark the provider unavailable so
        ``BrowserManager._get_provider()`` falls back to the
        next provider instead of surfacing a raw exception
        from what looks like a normal ``search()`` call.
        """
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            # Item 13B (C5): bound browser startup, and make the context
            # itself carry default action and navigation timeouts so no
            # later call relies on remembering to pass one.
            self._browser = self._playwright.chromium.launch(
                headless=self._resolve_headless(),
                timeout=self.LAUNCH_TIMEOUT_MS,
            )
            self._context = self._browser.new_context()
            try:
                self._context.set_default_timeout(self.DEFAULT_TIMEOUT_MS)
                self._context.set_default_navigation_timeout(
                    self.NAVIGATION_TIMEOUT_MS
                )
            except Exception:
                # Older Playwright builds may lack these; the explicit
                # per-call timeouts below still apply.
                pass
            self._page = self._context.new_page()
        except Exception:
            # Mark unavailable so manager falls back.
            self._available = False
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None
            self._playwright = None
            raise

    def _get_page(self):
        self._ensure_browser()
        return self._page

    def _is_browser_alive(self) -> bool:
        """Check if the Playwright browser connection is still alive.

        Phase 5 Part 5: When the browser process dies externally
        (killed, crashed, OOM), the Playwright connection is broken.
        We detect this by probing the context — if it's closed or
        unreachable, the provider is dead and the dispatch layer
        must be allowed to fall back to the next provider.

        Returns True if the browser is healthy, False if dead.
        """
        if self._browser is None or self._context is None:
            return False
        try:
            connection = getattr(
                getattr(self._browser, "_impl_obj", None),
                "_connection",
                None,
            )
            process = getattr(connection, "_proc", None)
            if process is not None and not process.is_alive():
                self._available = False
                return False
            if hasattr(self._browser, "is_connected"):
                if not self._browser.is_connected():
                    self._available = False
                    return False
            _ = self._context.pages
            if self._page is not None and hasattr(self._page, "title"):
                _ = self._page.title()
            return True
        except Exception:
            self._available = False
            return False

    def _is_connection_death(self, exc: Exception) -> bool:
        """Check if an exception indicates the browser connection has died.

        Phase 5 Part 5: Playwright sync API caches connection state,
        so probing with `_is_browser_alive()` may return True even
        when the transport is dead.  Instead, we check the exception
        itself for definitive connection-death signals:
        - greenlet.error with "cannot switch" = transport thread exited
        - TargetClosedError = page/context/browser was closed
        - Error with "Target closed" or "Browser closed" = connection dead
        - OSError/ConnectionError = underlying socket/pipe broken
        """
        import greenlet as _gl
        from playwright._impl._errors import Error as PwError

        # greenlet thread death = transport is gone
        if isinstance(exc, _gl.error):
            return True

        # Playwright connection-closed errors
        if isinstance(exc, PwError):
            msg = str(exc).lower()
            if "target closed" in msg or "browser closed" in msg:
                return True
            if "connection" in msg and ("closed" in msg or "lost" in msg):
                return True

        # Playwright TargetClosedError (subclass of PwError)
        try:
            from playwright._impl._errors import TargetClosedError
            if isinstance(exc, TargetClosedError):
                return True
        except ImportError:
            pass

        # Underlying OS/network errors
        if isinstance(exc, (OSError, ConnectionError, BrokenPipeError)):
            return True

        return False

    def open_url(self, url: str) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                # Item 13B (C5): explicit navigation timeout.
                # `wait_until="networkidle"` on a page that keeps a
                # websocket or long-poll open NEVER settles, so without
                # an explicit bound this call can wait indefinitely.
                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.NAVIGATION_TIMEOUT_MS,
                )
                actual_url = str(page.url)
                verified = bool(
                    actual_url
                    and (
                        actual_url.rstrip("/") == str(url).rstrip("/")
                        or actual_url.startswith(str(url))
                    )
                )
                return {
                    "success": True,
                    "operation": "browser.open_url",
                    "url": actual_url or url,
                    "requested_url": url,
                    "executed": True,
                    "verified": verified,
                    "verification_type": "url_readback",
                    "verification_reason": (
                        "Requested URL was read back after navigation."
                        if verified
                        else "Navigation completed, but the resulting URL did not match the request."
                    ),
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.open_url", "error": str(exc)}
 
    def navigate(self, url: str) -> Dict[str, Any]:
        return self.open_url(url)
 
    def search(self, query: str, engine: str = "google") -> Dict[str, Any]:
        domains = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q=",
            "youtube": "https://www.youtube.com/results?search_query=",
        }
        normalized_engine = str(engine).lower()
        base = domains.get(normalized_engine, domains["google"])
        from urllib.parse import quote_plus
        expected_url = base + quote_plus(query.strip())
        opened = self.open_url(expected_url)
        if not opened.get("success"):
            return opened
        try:
            page = self._get_page()
            actual_url = str(page.url)
            actual_title = str(page.title())
            url_verified = actual_url.startswith(base.split("?", 1)[0])
            verified = bool(url_verified and actual_title)
            return {
                **opened,
                "operation": "browser.search",
                "query": query.strip(),
                "engine": engine,
                "url": actual_url,
                "title": actual_title,
                "verified": verified,
                "verification_type": "search_url_and_title",
                "verification_reason": (
                    "Search URL and page title were read back."
                    if verified
                    else "Search page state could not be independently verified."
                ),
            }
        except Exception as exc:
            return {
                **opened,
                "operation": "browser.search",
                "query": query.strip(),
                "engine": engine,
                "verified": False,
                "verification_type": "search_state_unavailable",
                "verification_reason": str(exc),
            }
 
    def click(self, selector: str) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                page.click(selector, timeout=10000)
                result = {
                    "success": True,
                    "operation": "browser.click",
                    "selector": selector,
                    "verified": False,
                    "verification_type": "browser_dispatch_only",
                    "verification_reason": "Element presence does not prove the requested click postcondition.",
                }
                try:
                    loc = page.locator(selector)
                    count = loc.count()
                    result["element_found"] = count > 0
                    if count:
                        result["element_found"] = bool(
                            loc.first.is_visible() and loc.first.is_enabled()
                        )
                except Exception:
                    result["element_found"] = False
                return result
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.click", "error": str(exc)}
 
    def type_text(self, selector: str, text: str) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                page.fill(selector, text, timeout=10000)
                result = {"success": True, "operation": "browser.type", "selector": selector, "text": text}
                try:
                    loc = page.locator(selector)
                    actual_value = loc.input_value()
                    result["element_found"] = True
                    result["verified"] = (actual_value == text)
                    result["actual_value"] = actual_value
                    result["content_match"] = actual_value == text
                    result["verification_type"] = "input_value_readback"
                except Exception:
                    result["element_found"] = False
                    result["verified"] = False
                return result
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.type", "error": str(exc)}
 
    def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                # Pre-state readback for honest verification.
                try:
                    scroll_before = page.evaluate("window.scrollY")
                except Exception:
                    scroll_before = None
                for _ in range(amount):
                    if direction.lower() == "down":
                        page.keyboard.press("PageDown")
                    else:
                        page.keyboard.press("PageUp")
                result: Dict[str, Any] = {"success": True, "operation": "browser.scroll", "direction": direction, "amount": amount}
                # Post-state verification via scroll-offset readback.
                try:
                    scroll_after = page.evaluate("window.scrollY")
                except Exception:
                    scroll_after = None
                result["scroll_before"] = scroll_before
                result["scroll_after"] = scroll_after
                result["element_found"] = scroll_before is not None and scroll_after is not None
                if scroll_before is not None and scroll_after is not None:
                    result["scrolled"] = (scroll_after != scroll_before)
                    result["scroll_delta"] = scroll_after - scroll_before
                    result["scroll_position_changed"] = result["scrolled"]
                result["verified"] = bool(result.get("scrolled", False))
                return result
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.scroll", "error": str(exc)}
 
    def find_text(self, text: str) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                elements = page.locator(f"text={text}").all()
                return {"success": True, "operation": "browser.find", "text": text, "count": len(elements)}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.find", "error": str(exc)}
 
    def extract_text(self, selector: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                if selector:
                    elements = page.locator(selector).all()
                    text = " ".join([el.inner_text() for el in elements])
                else:
                    text = page.locator("body").inner_text()
                return {"success": True, "operation": "browser.extract", "text": text}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.extract", "error": str(exc)}
 
    def get_page_title(self) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                return {"success": True, "operation": "browser.get_title", "title": page.title()}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.get_title", "error": str(exc)}
 
    def get_page_url(self) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                return {"success": True, "operation": "browser.get_url", "url": page.url}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.get_url", "error": str(exc)}
 
    def switch_tab(self, index: int) -> Dict[str, Any]:
        with self._lock:
            try:
                pages = self._context.pages
                if 0 <= index < len(pages):
                    self._page = pages[index]
                    self._page.bring_to_front()
                    actual_url = str(self._page.url)
                    actual_title = str(self._page.title())
                    tabs = [
                        {
                            "index": tab_index,
                            "url": str(tab.url),
                            "title": str(tab.title()),
                            "active": tab == self._page,
                        }
                        for tab_index, tab in enumerate(self._context.pages)
                    ]
                    verified = bool(tabs[index].get("active") and actual_url)
                    return {
                        "success": True,
                        "operation": "browser.switch_tab",
                        "index": index,
                        "url": actual_url,
                        "title": actual_title,
                        "tabs": tabs,
                        "verified": verified,
                        "tab_state_verified": verified,
                        "verification_type": "tab_state_readback",
                    }
                return {"success": False, "operation": "browser.switch_tab", "error": f"Tab index {index} out of range (0-{len(pages)-1})"}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.switch_tab", "error": str(exc)}
 
    def open_tab(self, url: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                new_page = self._context.new_page()
                if url:
                    # Item 13B (C5): same explicit navigation bound.
                    new_page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=self.NAVIGATION_TIMEOUT_MS,
                    )
                self._page = new_page
                actual_url = str(new_page.url)
                actual_title = str(new_page.title())
                tab_index = len(self._context.pages) - 1
                url_matches = not url or actual_url.rstrip("/") == str(url).rstrip("/") or actual_url.startswith(str(url))
                verified = bool(
                    new_page in self._context.pages
                    and actual_url
                    and url_matches
                )
                return {
                    "success": True,
                    "operation": "browser.open_tab",
                    "url": actual_url or url,
                    "requested_url": url,
                    "title": actual_title,
                    "tab_index": tab_index,
                    "verified": verified,
                    "tab_state_verified": verified,
                    "verification_type": "tab_state_readback",
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.open_tab", "error": str(exc)}
 
    def close_tab(self, index: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                pages = self._context.pages
                if not pages:
                    return {"success": False, "operation": "browser.close_tab", "error": "No tabs open"}

                before_count = len(pages)
                if index is not None and not 0 <= index < before_count:
                    return {
                        "success": False,
                        "operation": "browser.close_tab",
                        "error": f"Tab index {index} out of range (0-{before_count - 1})",
                    }
                if index is None:
                    self._page.close()
                else:
                    pages[index].close()
                pages = self._context.pages
                if pages and self._page not in pages:
                    self._page = pages[0]
                verified = len(pages) == before_count - 1
                return {
                    "success": verified,
                    "operation": "browser.close_tab",
                    "index": index,
                    "before_count": before_count,
                    "count": len(pages),
                    "verified": verified,
                    "tab_state_verified": verified,
                    "verification_type": "tab_count_readback",
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.close_tab", "error": str(exc)}
 
    def get_tabs(self) -> Dict[str, Any]:
        with self._lock:
            try:
                pages = self._context.pages
                tabs = []
                for i, page in enumerate(pages):
                    tabs.append({
                        "index": i,
                        "url": page.url,
                        "title": page.title(),
                        "active": page == self._page
                    })
                return {
                    "success": True,
                    "operation": "browser.get_tabs",
                    "tabs": tabs,
                    "count": len(tabs),
                    "verified": True,
                    "tab_state_verified": True,
                    "verification_type": "tab_state_readback",
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.get_tabs", "error": str(exc)}
 
    def wait_for_element(self, selector: str, timeout: float = 10.0) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                page.wait_for_selector(selector, timeout=timeout * 1000)
                return {"success": True, "operation": "browser.wait", "selector": selector, "found": True}
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.wait", "error": str(exc)}
  
    def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                if path is None:
                    import tempfile
                    # Item 24A (C26): mkstemp creates the file atomically.
                    # mktemp only INVENTED a name -- a check-then-create
                    # race another process could win before the write.
                    fd, path = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                page.screenshot(path=path)
                # Item 24A (C26): the call returning is not success --
                # the artifact decides. mkstemp pre-creates a zero-byte
                # file, so an unwritten screenshot fails the size check.
                artifact_ok = os.path.isfile(path) and os.path.getsize(path) > 0
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {
                    "success": False,
                    "operation": "browser.screenshot",
                    "error": str(exc),
                    "executed": False,
                    "verified": False,
                }
            if not artifact_ok:
                return {
                    "success": False,
                    "operation": "browser.screenshot",
                    "path": path,
                    "error": f"Screenshot artifact missing or empty at '{path}'.",
                    "executed": False,
                    "verified": False,
                    "verification_type": "screenshot_artifact_file",
                }
            return {
                "success": True,
                "operation": "browser.screenshot",
                "path": path,
                "executed": True,
                "verified": True,
                "verification_type": "screenshot_artifact_file",
            }
  
    def select(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                page = self._get_page()
                if value is not None:
                    page.select_option(selector, value=value, timeout=10000)
                    method = "value"
                elif label is not None:
                    page.select_option(selector, label=label, timeout=10000)
                    method = "label"
                elif index is not None:
                    page.select_option(selector, index=index, timeout=10000)
                    method = "index"
                else:
                    return {"success": False, "operation": "browser.select", "error": "No selection method specified (value, label, or index required)"}
                locator = page.locator(selector).first
                actual_value = str(locator.input_value())
                actual_label = str(locator.evaluate("el => el.selectedOptions[0] ? el.selectedOptions[0].textContent : ''"))
                actual_index = int(locator.evaluate("el => el.selectedIndex"))
                verified = (
                    actual_value == str(value)
                    if method == "value"
                    else actual_label == str(label)
                    if method == "label"
                    else actual_index == int(index)
                )
                return {
                    "success": True,
                    "operation": "browser.select",
                    "selector": selector,
                    "method": method,
                    "value": value,
                    "label": label,
                    "index": index,
                    "actual_value": actual_value,
                    "actual_label": actual_label,
                    "actual_index": actual_index,
                    "verified": verified,
                    "selection_verified": verified,
                    "verification_type": "selection_state_readback",
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.select", "error": str(exc)}
  
    def download(self, url: str, save_path: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                import os
                import tempfile
                from pathlib import Path
                page = self._get_page()
                if save_path is None:
                    save_path = os.path.join(tempfile.gettempdir(), os.path.basename(url) or "download")
                destination = Path(save_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with page.expect_download(timeout=30000) as download_info:
                    # Item 13B (C5): explicit bound.
                    # `expect_download(timeout=...)` bounds the
                    # DOWNLOAD, not this goto. `wait_until="commit"`
                    # returns once the response starts, which is what a
                    # download wants, but a connection that never
                    # commits would still block here indefinitely.
                    page.goto(
                        url,
                        wait_until="commit",
                        timeout=self.NAVIGATION_TIMEOUT_MS,
                    )
                download = download_info.value
                download.save_as(str(destination))
                exists = destination.is_file() and destination.stat().st_size > 0
                return {
                    "success": exists,
                    "operation": "browser.download",
                    "url": url,
                    "save_path": str(destination),
                    "file_size": destination.stat().st_size if exists else 0,
                    "verified": exists,
                    "verification_type": "playwright_download",
                }
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.download", "error": str(exc)}
  
    def upload(self, selector: str, file_path: str) -> Dict[str, Any]:
        with self._lock:
            try:
                import os
                page = self._get_page()
                if not os.path.exists(file_path):
                    return {"success": False, "operation": "browser.upload", "error": f"File not found: {file_path}"}
                abs_path = os.path.abspath(file_path)
                page.set_input_files(selector, abs_path, timeout=10000)
                result = {
                    "success": True,
                    "operation": "browser.upload",
                    "selector": selector,
                    "file_path": file_path,
                    "verified": False,
                    "verification_type": "input_readback_remote_unverified",
                    "verification_reason": "The file input can be read, but remote upload completion cannot be proven.",
                }
                try:
                    loc = page.locator(selector)
                    result["element_found"] = loc.count() > 0
                    files = loc.evaluate("el => el.files ? el.files.length : 0")
                    result["input_file_count"] = files
                    result["input_readback_verified"] = files > 0
                except Exception:
                    result["element_found"] = False
                    result["input_file_count"] = 0
                    result["input_readback_verified"] = False
                return result
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.upload", "error": str(exc)}

    def get_page_state(self) -> Dict[str, Any]:
        """Phase 8: Capture full browser page state.

        Returns title, URL, element count, visible text summary,
        and DOM snapshot for observation/verification.
        """
        with self._lock:
            try:
                page = self._get_page()
                state: Dict[str, Any] = {
                    "success": True,
                    "operation": "browser.get_page_state",
                    "title": page.title(),
                    "url": page.url,
                }
                try:
                    state["element_count"] = page.locator("*").count()
                except Exception:
                    state["element_count"] = -1
                try:
                    body_text = page.locator("body").inner_text()
                    state["text_length"] = len(body_text)
                    state["text_preview"] = body_text[:500]
                except Exception:
                    state["text_length"] = 0
                    state["text_preview"] = ""
                try:
                    forms = page.locator("form").count()
                    inputs = page.locator("input").count()
                    buttons = page.locator("button").count()
                    links = page.locator("a").count()
                    state["forms"] = forms
                    state["inputs"] = inputs
                    state["buttons"] = buttons
                    state["links"] = links
                except Exception:
                    state["forms"] = 0
                    state["inputs"] = 0
                    state["buttons"] = 0
                    state["links"] = 0
                try:
                    state["cookies"] = len(page.context.cookies())
                except Exception:
                    state["cookies"] = 0
                return state
            except Exception as exc:
                if self._is_connection_death(exc):
                    raise
                return {"success": False, "operation": "browser.get_page_state", "error": str(exc)}

    def close(self) -> None:
        """Close the browser and clean up."""
        with self._lock:
            try:
                if self._context:
                    self._context.close()
                if self._browser:
                    self._browser.close()
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            finally:
                self._browser = None
                self._context = None
                self._page = None
                self._playwright = None