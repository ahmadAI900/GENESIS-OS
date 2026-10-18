"""Genesis OS — Selenium Browser Provider.

Optional provider for advanced browser automation using Selenium.
Only loads if selenium is installed.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .browser_manager import BrowserProvider

# Module-level cache: probe result computed once, reused by all
# SeleniumBrowserProvider instances.  On Windows the subprocess
# spawn + reimport takes ~5s per probe, so caching avoids the
# cost on every BrowserManager() instantiation.
_probe_cache: int = -1  # -1 = not yet probed

# A TIMEOUT IS NOT AN ANSWER -- see the identical note in
# browser_playwright.py. A probe that exceeds its 5s join bound under
# CPU load has not established that ChromeDriver is missing, so it is
# cached only for the TTL and then re-probed.
_PROBE_CACHE_TTL_SECONDS = 60.0
_probe_cache_kind: str = ""      # "" | "definitive" | "timeout"
_probe_cache_at: float = 0.0     # monotonic, when the result was stored


def _probe_cache_is_valid() -> bool:
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


def _probe_chromedriver_subprocess(result_ref):
    """Target function for multiprocessing ChromeDriver probe.

    Must be defined at module level (not nested) so it can be
    pickled on Windows where multiprocessing uses 'spawn'.
    """
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
        if path:
            import os as _os
            result_ref.value = 1 if _os.path.isfile(path) else 0
        else:
            result_ref.value = 0
    except Exception:
        result_ref.value = 0


class SeleniumBrowserProvider(BrowserProvider):
    """Selenium-based browser automation provider."""

    name = "selenium"

    def __init__(self):
        self._driver = None
        self._lock = threading.RLock()
        # Item 15C (C13): why the provider is unavailable, when it is.
        # Never advertised available while carrying a startup failure.
        self.unavailable_reason: Optional[str] = None
        self._available = self._check_availability()
        if not self._available:
            self.unavailable_reason = self.unavailable_reason or (
                "selenium or a chromedriver binary is not present"
            )

    def _check_availability(self) -> bool:
        """Verify the ``selenium`` Python package imports AND a
        ChromeDriver binary is actually usable.

        Uses a module-level cache so the expensive subprocess
        probe runs at most once per process, not per instance --
        unless the probe TIMED OUT, which is re-tried after the TTL.
        """
        if _probe_cache_is_valid():
            return bool(_probe_cache)
        try:
            import selenium  # noqa: F401
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            _store_probe_result(0, "definitive")
            return False
        import multiprocessing as _mp
        result = _mp.Value("i", 0)
        proc = _mp.Process(target=_probe_chromedriver_subprocess, args=(result,))
        proc.start()
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            _store_probe_result(0, "timeout")
            return False
        _store_probe_result(1 if result.value else 0, "definitive")
        return bool(_probe_cache)

    @property
    def available(self) -> bool:
        return self._available

    def _mark_unavailable(self, reason: str) -> None:
        """Record a proven startup failure and stop advertising.

        Item 15C (C13): the point of the item. A provider that has
        been shown not to start must not keep reporting
        `available=True`; that is how a provider that could never work
        sat in the rotation looking healthy for so long.
        """
        self._available = False
        self.unavailable_reason = reason

    # Item 13B (C5): real driver-level timeouts.
    #
    # Same reasoning as the Playwright provider: the manager dispatches
    # Selenium in-process because WebDriver is bound to its creating
    # thread, so the bound has to live in the driver. These are genuine
    # WebDriver timeouts -- the remote end raises on them rather than
    # the local wrapper wishing it could.
    PAGE_LOAD_TIMEOUT_S = 30
    SCRIPT_TIMEOUT_S = 30
    IMPLICIT_WAIT_S = 0  # explicit waits only; never mix with implicit
    DRIVER_STARTUP_TIMEOUT_S = 60
    DRIVER_DOWNLOAD_TIMEOUT_S = 120

    def _get_driver(self):
        """Get or create the WebDriver instance.

        Item 13B (C5): every unbounded step is now bounded.

        `ChromeDriverManager().install()` DOWNLOADS chromedriver over the
        network on a cache miss. Unbounded, that is the single easiest
        way for driver creation to hang forever -- on a captive portal,
        a proxy that stalls, or a machine with no route out. It is pure
        network IO with no thread affinity, so it is safe to run in a
        worker and abandon; a download we gave up on is not a driver, so
        nothing is left half-attached to the caller.

        Item 15C (C13): the provider could never start AT ALL, while
        advertising itself available.

        `webdriver.Chrome` was called with `service_timeout=...`.
        Selenium 4.48's signature is `(options, service, keep_alive)` --
        there is no such parameter, so EVERY call raised

            TypeError: WebDriver.__init__() got an unexpected
                       keyword argument 'service_timeout'

        before a browser was ever launched. The availability probe does
        not create a driver (it only imports selenium and looks for a
        chromedriver binary), so it returned True and the provider
        advertised itself as usable. The per-call try/except in every
        provider method then swallowed the TypeError into a generic
        "provider failed" result. The provider was permanently,
        silently non-functional and reported itself healthy.

        The kwarg is gone. The startup it was trying to bound is now
        bounded properly by `_create_driver`, and a creation that fails
        marks the provider UNAVAILABLE rather than leaving a provider
        that claims to work.
        """
        if self._driver is None:
            from selenium.webdriver.chrome.options import Options

            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            # Uncomment for headless: options.add_argument("--headless")

            driver_path = self._bounded_driver_download()

            self._driver = self._create_driver(driver_path, options)

            # Item 13B (C5): bound the remote end from the start, so a
            # page that never finishes loading cannot hold a call open
            # indefinitely. These raise WebDriverTimeoutException, which
            # the providers already handle as a provider failure.
            try:
                self._driver.set_page_load_timeout(self.PAGE_LOAD_TIMEOUT_S)
                self._driver.set_script_timeout(self.SCRIPT_TIMEOUT_S)
                self._driver.implicitly_wait(self.IMPLICIT_WAIT_S)
            except Exception:
                # A remote that rejects these is still usable; the
                # manager-level overrun check (Item 13B) still refuses
                # to certify a late result.
                pass
        return self._driver

    # ---------------------------------------------------------------
    # Item 15C (C13): driver CREATION, bounded.
    # ---------------------------------------------------------------
    #
    # Separate method so it is one seam: a test can substitute a fake
    # driver factory and exercise the whole availability contract
    # without a browser being installed.
    #
    # THREAD AFFINITY, checked rather than assumed. Item 13B's comment
    # says WebDriver is "bound to its creating thread". That is true of
    # Playwright's sync API; for Selenium it is not the reason the
    # manager dispatches in-process, and creating the driver in a worker
    # and using it from the caller is safe -- Selenium holds no
    # thread-local state (verified: zero modules under selenium/ use
    # threading.local) and its RemoteConnection talks HTTP through a
    # thread-safe urllib3 PoolManager. Concurrent use of one driver from
    # two threads is still not supported, and never happens here --
    # every provider method is already serialised behind `self._lock`.
    #
    # If the join times out, the worker is abandoned (daemon). Chrome may
    # still be starting up in the background; we simply stop waiting and
    # report the driver as unavailable rather than handing back something
    # that may never be usable.
    def _create_driver(self, driver_path: str, options: Any):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service

        return self._bounded_chrome_call(
            webdriver.Chrome,
            Service,
            driver_path,
            options,
        )

    def _bounded_chrome_call(
        self,
        chrome_factory: Any,
        service_cls: Any,
        driver_path: str,
        options: Any,
    ):
        box: Dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["driver"] = chrome_factory(
                    service=service_cls(driver_path),
                    options=options,
                )
            except Exception as exc:
                # Captured, not raised: this runs off the main thread.
                # `Exception`, not `BaseException` -- a KeyboardInterrupt
                # belongs to the main thread and must not be swallowed
                # here. If the worker dies without setting `driver`,
                # the None check below raises, so nothing is invented.
                box["error"] = exc

        worker = threading.Thread(
            target=_worker,
            daemon=True,
            name="selenium-driver-start",
        )
        worker.start()
        worker.join(self.DRIVER_STARTUP_TIMEOUT_S)

        if worker.is_alive():
            raise TimeoutError(
                f"webdriver.Chrome did not return within "
                f"{self.DRIVER_STARTUP_TIMEOUT_S}s; treating the "
                f"driver as unavailable rather than hanging"
            )

        error = box.get("error")
        if error is not None:
            raise error

        driver = box.get("driver")
        if driver is None:
            raise RuntimeError(
                "webdriver.Chrome returned without a driver"
            )
        return driver

    def _bounded_driver_download(self) -> str:
        """Return a chromedriver path, giving up after a fixed budget.

        Raises on timeout rather than returning a path we do not have,
        so a stalled download surfaces as driver-creation failure instead
        of an unbounded block.
        """
        from concurrent.futures import (
            ThreadPoolExecutor,
            TimeoutError as FuturesTimeoutError,
        )

        from webdriver_manager.chrome import ChromeDriverManager

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                ChromeDriverManager().install
            )
            return future.result(timeout=self.DRIVER_DOWNLOAD_TIMEOUT_S)
        except FuturesTimeoutError as exc:
            raise TimeoutError(
                f"chromedriver download did not finish within "
                f"{self.DRIVER_DOWNLOAD_TIMEOUT_S}s; the driver is not "
                f"available rather than the caller hanging"
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
 
    def _ensure_driver(self):
        """Ensure driver is initialized.

        Item 15C (C13): a driver that cannot be created makes the
        provider UNAVAILABLE, permanently, instead of leaving it
        advertising `available=True` while every call fails inside a
        swallowed exception.

        The availability probe only checks that selenium imports and a
        chromedriver binary exists. Neither proves that
        `webdriver.Chrome(...)` will return a driver -- and for years it
        could not, because of an invalid kwarg. So a probe pass is a
        NECESSARY condition, not a sufficient one, and only an actual
        creation establishes it.
        """
        if self._driver is None:
            try:
                self._get_driver()
            except Exception as exc:
                # `Exception`, not `BaseException`: a Ctrl-C during
                # driver startup is the user interrupting, not evidence
                # that this provider is broken, and must not permanently
                # mark it unavailable.
                self._mark_unavailable(f"driver creation failed: {exc}")
                raise

    def _is_driver_alive(self) -> bool:
        if self._driver is None:
            return False
        try:
            _ = self._driver.title
            return True
        except Exception:
            return False

    def _is_connection_death(self, exc: Exception) -> bool:
        if self._driver is None:
            return True
        exc_name = type(exc).__name__
        if exc_name in ("StaleElementReferenceException",
                         "NoSuchWindowException",
                         "SessionNotCreatedException",
                         "WebDriverException"):
            msg = str(exc).lower()
            if any(k in msg for k in ("session", "stale", "no such window",
                                        "disconnected", "detached",
                                        "target closed", "connection")):
                return True
        return False

    def open_url(self, url: str) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            self._driver.get(url)
            actual_url = str(self._driver.current_url)
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
            if not self._is_driver_alive():
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
            actual_url = str(self._driver.current_url)
            actual_title = str(self._driver.title)
            verified = bool(
                actual_url.startswith(base.split("?", 1)[0])
                and actual_title
            )
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
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            element = WebDriverWait(self._driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            element.click()
            result = {
                "success": True,
                "operation": "browser.click",
                "selector": selector,
                "verified": False,
                "verification_type": "browser_dispatch_only",
                "verification_reason": "Element presence does not prove the requested click postcondition.",
            }
            try:
                elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
                result["element_found"] = len(elements) > 0
                if elements:
                    result["element_found"] = bool(
                        elements[0].is_displayed() and elements[0].is_enabled()
                    )
            except Exception:
                result["element_found"] = False
            return result
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.click", "error": str(exc)}
 
    def type_text(self, selector: str, text: str) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            element = WebDriverWait(self._driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            element.clear()
            element.send_keys(text)
            result = {"success": True, "operation": "browser.type", "selector": selector, "text": text}
            # Real post-state verification: read back the input value
            # to confirm the text was actually accepted by the element.
            try:
                elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    actual_value = elements[0].get_attribute("value") or ""
                    result["element_found"] = True
                    result["verified"] = (actual_value == text)
                    result["actual_value"] = actual_value
                    result["content_match"] = actual_value == text
                    result["verification_type"] = "input_value_readback"
                else:
                    result["element_found"] = False
                    result["verified"] = False
            except Exception:
                result["element_found"] = False
                result["verified"] = False
            return result
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.type", "error": str(exc)}
 
    def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.by import By

            body = self._driver.find_element(By.TAG_NAME, "body")
            # Pre-state readback for honest verification.
            try:
                scroll_before = self._driver.execute_script("return window.pageYOffset;")
            except Exception:
                scroll_before = None
            for _ in range(amount):
                if direction.lower() == "down":
                    body.send_keys(Keys.PAGE_DOWN)
                else:
                    body.send_keys(Keys.PAGE_UP)
            result: Dict[str, Any] = {"success": True, "operation": "browser.scroll", "direction": direction, "amount": amount}
            # Post-state verification via scroll-offset readback.
            try:
                scroll_after = self._driver.execute_script("return window.pageYOffset;")
            except Exception:
                scroll_after = None
            result["scroll_before"] = scroll_before
            result["scroll_after"] = scroll_after
            result["element_found"] = scroll_before is not None and scroll_after is not None
            if scroll_before is not None and scroll_after is not None:
                try:
                    result["scrolled"] = (scroll_after != scroll_before)
                    result["scroll_delta"] = scroll_after - scroll_before
                    result["scroll_position_changed"] = result["scrolled"]
                except Exception:
                    pass
            result["verified"] = bool(result.get("scrolled", False))
            return result
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.scroll", "error": str(exc)}
    def find_text(self, text: str) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            safe_text = text.replace("'", "\\'").replace('"', '\\"')
            xpath = f"//*[contains(text(), '{safe_text}')]"
            elements = self._driver.find_elements(By.XPATH, xpath)
            return {"success": True, "operation": "browser.find", "text": text, "count": len(elements)}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.find", "error": str(exc)}
 
    def extract_text(self, selector: Optional[str] = None) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
 
            if selector:
                elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
                text = " ".join([el.text for el in elements if el.text])
            else:
                body = self._driver.find_element(By.TAG_NAME, "body")
                text = body.text
            return {"success": True, "operation": "browser.extract", "text": text}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.extract", "error": str(exc)}
 
    def get_page_title(self) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            return {"success": True, "operation": "browser.get_title", "title": self._driver.title}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.get_title", "error": str(exc)}
 
    def get_page_url(self) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            return {"success": True, "operation": "browser.get_url", "url": self._driver.current_url}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.get_url", "error": str(exc)}
 
    def switch_tab(self, index: int) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            handles = self._driver.window_handles
            if 0 <= index < len(handles):
                self._driver.switch_to.window(handles[index])
                tabs = []
                for tab_index, handle in enumerate(handles):
                    self._driver.switch_to.window(handle)
                    tabs.append({
                        "index": tab_index,
                        "url": self._driver.current_url,
                        "title": self._driver.title,
                        "active": handle == self._driver.current_window_handle,
                    })
                self._driver.switch_to.window(handles[index])
                verified = bool(tabs[index].get("active") and tabs[index].get("url"))
                return {
                    "success": True,
                    "operation": "browser.switch_tab",
                    "index": index,
                    "url": self._driver.current_url,
                    "title": self._driver.title,
                    "tabs": tabs,
                    "verified": verified,
                    "tab_state_verified": verified,
                    "verification_type": "tab_state_readback",
                }
            return {"success": False, "operation": "browser.switch_tab", "error": f"Tab index {index} out of range (0-{len(handles)-1})"}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.switch_tab", "error": str(exc)}
 
    def open_tab(self, url: Optional[str] = None) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            self._driver.execute_script("window.open('');")
            handles = self._driver.window_handles
            self._driver.switch_to.window(handles[-1])
            if url:
                self._driver.get(url)
            actual_url = str(self._driver.current_url)
            actual_title = str(self._driver.title)
            tab_index = len(handles) - 1
            url_matches = not url or actual_url.rstrip("/") == str(url).rstrip("/") or actual_url.startswith(str(url))
            verified = bool(actual_url and url_matches)
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
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.open_tab", "error": str(exc)}
 
    def close_tab(self, index: Optional[int] = None) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            handles = self._driver.window_handles
            if not handles:
                return {"success": False, "operation": "browser.close_tab", "error": "No tabs open"}
 
            before_count = len(handles)
            if index is not None and not 0 <= index < before_count:
                return {
                    "success": False,
                    "operation": "browser.close_tab",
                    "error": f"Tab index {index} out of range (0-{before_count - 1})",
                }
            if index is None:
                self._driver.close()
            else:
                current_handle = self._driver.current_window_handle
                target_handle = handles[index]
                self._driver.switch_to.window(target_handle)
                self._driver.close()
            handles = self._driver.window_handles
            if handles:
                self._driver.switch_to.window(handles[0])
            verified = len(handles) == before_count - 1
            return {
                "success": verified,
                "operation": "browser.close_tab",
                "index": index,
                "before_count": before_count,
                "count": len(handles),
                "verified": verified,
                "tab_state_verified": verified,
                "verification_type": "tab_count_readback",
            }
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.close_tab", "error": str(exc)}
 
    def get_tabs(self) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            handles = self._driver.window_handles
            tabs = []
            for i, handle in enumerate(handles):
                self._driver.switch_to.window(handle)
                tabs.append({
                    "index": i,
                    "url": self._driver.current_url,
                    "title": self._driver.title,
                    "active": handle == self._driver.current_window_handle
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
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.get_tabs", "error": str(exc)}
 
    def wait_for_element(self, selector: str, timeout: float = 10.0) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
 
            element = WebDriverWait(self._driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            return {"success": True, "operation": "browser.wait", "selector": selector, "found": True}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.wait", "error": str(exc)}
 
    def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            if path is None:
                import tempfile
                path = tempfile.mktemp(suffix=".png")
            self._driver.save_screenshot(path)
            return {"success": True, "operation": "browser.screenshot", "path": path}
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.screenshot", "error": str(exc)}
 
    def select(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, index: Optional[int] = None) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait, Select
            from selenium.webdriver.support import expected_conditions as EC

            element = WebDriverWait(self._driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            select = Select(element)

            if value is not None:
                select.select_by_value(value)
                method = "value"
            elif label is not None:
                select.select_by_visible_text(label)
                method = "label"
            elif index is not None:
                select.select_by_index(index)
                method = "index"
            else:
                return {"success": False, "operation": "browser.select", "error": "No selection method specified (value, label, or index required)"}
            selected = select.first_selected_option
            actual_value = str(selected.get_attribute("value") or "")
            actual_label = str(selected.text or "")
            actual_index = int(self._driver.execute_script("return arguments[0].selectedIndex;", element))
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
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.select", "error": str(exc)}
 
    def upload(self, selector: str, file_path: str) -> Dict[str, Any]:
        try:
            self._ensure_driver()
            import os
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            if not os.path.exists(file_path):
                return {"success": False, "operation": "browser.upload", "error": f"File not found: {file_path}"}

            element = WebDriverWait(self._driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            element.send_keys(os.path.abspath(file_path))
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
                elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    value = elements[0].get_attribute("value") or ""
                    result["element_found"] = True
                    result["input_value"] = value
                    result["input_readback_verified"] = bool(value)
                else:
                    result["element_found"] = False
                    result["input_readback_verified"] = False
            except Exception:
                result["element_found"] = False
                result["input_readback_verified"] = False
            return result
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.upload", "error": str(exc)}

    def get_page_state(self) -> Dict[str, Any]:
        """Phase 8: Capture full browser page state."""
        try:
            self._ensure_driver()
            from selenium.webdriver.common.by import By
            state: Dict[str, Any] = {
                "success": True,
                "operation": "browser.get_page_state",
                "title": self._driver.title,
                "url": self._driver.current_url,
            }
            try:
                elements = self._driver.find_elements(By.CSS_SELECTOR, "*")
                state["element_count"] = len(elements)
            except Exception:
                state["element_count"] = -1
            try:
                body = self._driver.find_element(By.TAG_NAME, "body")
                body_text = body.text
                state["text_length"] = len(body_text)
                state["text_preview"] = body_text[:500]
            except Exception:
                state["text_length"] = 0
                state["text_preview"] = ""
            try:
                state["forms"] = len(self._driver.find_elements(By.TAG_NAME, "form"))
                state["inputs"] = len(self._driver.find_elements(By.TAG_NAME, "input"))
                state["buttons"] = len(self._driver.find_elements(By.TAG_NAME, "button"))
                state["links"] = len(self._driver.find_elements(By.TAG_NAME, "a"))
            except Exception:
                state["forms"] = 0
                state["inputs"] = 0
                state["buttons"] = 0
                state["links"] = 0
            try:
                state["cookies"] = len(self._driver.get_cookies())
            except Exception:
                state["cookies"] = 0
            return state
        except Exception as exc:
            if not self._is_driver_alive():
                raise
            return {"success": False, "operation": "browser.get_page_state", "error": str(exc)}

    def close(self) -> None:
        """Close the browser and clean up."""
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None