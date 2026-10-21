"""Item 24A (C26): browser.screenshot reported success with no artifact.

Both real browser providers ended their screenshot() methods with:

    page.screenshot(path=path)                      # playwright
    return {"success": True, "operation": "browser.screenshot", "path": path}

after building the default path with ``tempfile.mktemp(suffix=".png")``
-- a call the Python docs deprecate precisely because it is a
check-then-create race (TOCTOU): between the NAME being generated and
the browser writing it, another process can create (or redirect) that
path.

Nothing ever asked whether bytes reached the disk:

  * the browser call not raising was the whole "success": selenium's
    ``save_screenshot`` RETURNS False on failure and the return value
    was discarded, so a driver that silently failed still produced
    ``{"success": True}``;
  * ``verified`` was never set at the provider level and ``executed``
    was absent, so the executor derived executed=False / verified=False
    while still seeing success=True with no error key -- the
    honest-looking status "success" for a screenshot that wrote
    nothing.

The contract asserted here:

    writes real bytes       -> success/executed/verified True, and the
                               ARTIFACT re-read from disk carries them
    writes nothing          -> success/executed/verified False + error
    default path            -> tempfile.mkstemp (atomic create), never
                               the racy tempfile.mktemp
    empty pre-created file  -> rejected: mkstemp's zero-byte file must
                               not be mistaken for a screenshot
    raises                  -> failure dict with honest executed /
                               verified flags

All ten tests fail before this item: the old dict has no verified /
executed keys at all, reports success for missing files, and calls
mktemp.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import time
from pathlib import Path

import pytest

PLAYWRIGHT = "genesis_os.browser_playwright"
SELENIUM = "genesis_os.browser_selenium"
MODULES = [PLAYWRIGHT, SELENIUM]

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"C26" * 64


class _FakePage:
    """Playwright page double. ``mode``: write | silent | raise."""

    def __init__(self, mode):
        self._mode = mode

    def screenshot(self, path=None, **kwargs):
        if self._mode == "write":
            Path(path).write_bytes(PNG_BYTES)
        elif self._mode == "raise":
            raise RuntimeError("simulated page.screenshot failure")
        # "silent": the call returns and NOTHING reaches the disk.


class _FakeDriver:
    """Selenium driver double.

    ``save_screenshot`` returns a bool exactly like the real driver --
    and silent mode returns False, the real signature of a driver that
    failed without raising (the return value the old code discarded).
    """

    def __init__(self, mode):
        self._mode = mode

    def save_screenshot(self, path):
        if self._mode == "write":
            Path(path).write_bytes(PNG_BYTES)
            return True
        if self._mode == "raise":
            raise RuntimeError("simulated save_screenshot failure")
        return False


def _provider(monkeypatch, module_name, mode):
    """Real provider instance with fake page/driver attached.

    The constructor's availability probe spawns a subprocess; its
    result is cached at module level, so the cache is seeded to
    "present" -- construction stays instant and offline (the pattern
    test_browser_degraded_mode already uses).
    """
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "_probe_cache", 1, raising=False)
    monkeypatch.setattr(
        module, "_probe_cache_kind", "definitive", raising=False
    )
    monkeypatch.setattr(
        module, "_probe_cache_at", time.monotonic(), raising=False
    )
    if module_name == PLAYWRIGHT:
        provider = module.PlaywrightBrowserProvider()
        provider._get_page = lambda: _FakePage(mode)
    else:
        provider = module.SeleniumBrowserProvider()
        provider._ensure_driver = lambda: None
        provider._driver = _FakeDriver(mode)
        provider._is_driver_alive = lambda: True
    return provider


# --------------------------------------------------------------------------
# The repro: a screenshot that produced no file was still a success.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", MODULES)
def test_a_screenshot_that_writes_nothing_is_not_success(
    module_name, tmp_path, monkeypatch
):
    provider = _provider(monkeypatch, module_name, "silent")
    target = str(tmp_path / "never_written.png")

    result = provider.screenshot(target)

    assert result["success"] is False, result
    assert result.get("verified") is False, result
    assert result.get("executed") is False, result
    assert not Path(target).exists(), (
        "the fake wrote nothing; the disk must agree"
    )
    assert result.get("error"), (
        "a failed screenshot must say why it failed"
    )


# --------------------------------------------------------------------------
# The positive case: verified means the bytes are on disk.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", MODULES)
def test_success_is_bound_to_the_artifact_on_disk(
    module_name, tmp_path, monkeypatch
):
    provider = _provider(monkeypatch, module_name, "write")
    target = str(tmp_path / "real_shot.png")

    result = provider.screenshot(target)

    assert result["success"] is True, result
    assert result.get("verified") is True, result
    assert result.get("executed") is True, result
    assert result.get("verification_type") == "screenshot_artifact_file", (
        result
    )
    # The verification is the FILE, not the flag: re-read the artifact.
    on_disk = Path(result["path"])
    assert on_disk.is_file()
    assert on_disk.stat().st_size > 0
    assert on_disk.read_bytes() == PNG_BYTES


# --------------------------------------------------------------------------
# The TOCTOU half: the default path must be created atomically.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", MODULES)
def test_the_default_path_is_created_atomically(module_name):
    module = importlib.import_module(module_name)
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    screenshot_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "screenshot"
    )
    called_attrs = {
        node.func.attr
        for node in ast.walk(screenshot_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    assert "mktemp" not in called_attrs, (
        "screenshot() still uses tempfile.mktemp -- a check-then-create "
        "race any process can win between name generation and the write"
    )
    assert "mkstemp" in called_attrs, (
        "screenshot() no longer creates its default path atomically"
    )


@pytest.mark.parametrize("module_name", MODULES)
def test_an_empty_default_artifact_is_not_success(
    module_name, monkeypatch
):
    provider = _provider(monkeypatch, module_name, "silent")

    result = provider.screenshot()  # path=None: the provider builds it

    on_disk = Path(result["path"])
    assert on_disk.exists(), (
        "the default path must be created up front (mkstemp) so an "
        "unwritten screenshot leaves a zero-byte file to be judged"
    )
    assert on_disk.stat().st_size == 0, (
        "the silent fake wrote nothing"
    )
    assert result["success"] is False, result
    assert result.get("verified") is False, result


# --------------------------------------------------------------------------
# Exceptions stay failures, with the flags stated honestly.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", MODULES)
def test_an_exception_is_a_failure_with_honest_flags(
    module_name, tmp_path, monkeypatch
):
    provider = _provider(monkeypatch, module_name, "raise")

    result = provider.screenshot(str(tmp_path / "boom.png"))

    assert result["success"] is False, result
    assert result.get("verified") is False, result
    assert result.get("executed") is False, result
    assert "simulated" in (result.get("error") or ""), result
