"""Regression guards for C37-C40: paths that read `verified` unbound."""

from __future__ import annotations

import threading

import pytest

from genesis_os.browser_playwright import PlaywrightBrowserProvider
from genesis_os.browser_selenium import SeleniumBrowserProvider
from genesis_os.clipboard_manager import ClipboardManager
from genesis_os.filesystem.folder_manager import FolderManager


class _Clipboard:
    def __init__(self, content):
        self._content = content

    def paste(self):
        return self._content


class _SeleniumElement:
    def __init__(self, value):
        self._value = value

    def clear(self):
        pass

    def send_keys(self, text):
        pass

    def get_attribute(self, name):
        return self._value


class _SeleniumDriver:
    def __init__(self, value):
        self._element = _SeleniumElement(value)

    def find_element(self, by, selector):
        return self._element

    def find_elements(self, by, selector):
        return [self._element]


class _PlaywrightInput:
    def __init__(self, value):
        self._value = value

    def input_value(self):
        return self._value


class _PlaywrightTypePage:
    def __init__(self, value):
        self._value = value

    def fill(self, selector, text, timeout=0):
        pass

    def locator(self, selector):
        return _PlaywrightInput(self._value)


class _PlaywrightFindPage:
    def __init__(self, count):
        self._count = count

    def locator(self, selector):
        page = self

        class _Locator:
            def all(self):
                return [object()] * page._count

        return _Locator()


def _playwright() -> PlaywrightBrowserProvider:
    provider = PlaywrightBrowserProvider.__new__(PlaywrightBrowserProvider)
    provider._lock = threading.RLock()
    return provider


def test_clipboard_paste_of_empty_content_reports_a_successful_query():
    manager = ClipboardManager.__new__(ClipboardManager)
    manager.available = True
    manager._pyperclip = _Clipboard("")

    result = manager.paste()

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["empty"] is True, result


def test_clipboard_paste_of_text_reports_a_successful_query():
    manager = ClipboardManager.__new__(ClipboardManager)
    manager.available = True
    manager._pyperclip = _Clipboard("hello")

    result = manager.paste()

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["content_preview"] == "hello", result


def test_folder_organize_already_organized_folder_is_a_success(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        FolderManager,
        "_validate",
        staticmethod(lambda path, **kwargs: {"allowed": True, "path": str(path)}),
    )

    result = FolderManager().organize(tmp_path)

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["organized_count"] == 0, result


@pytest.mark.parametrize(
    ("actual", "expected_success"),
    [("typed", True), ("different", False)],
)
def test_playwright_type_success_follows_the_input_readback(
    actual, expected_success
):
    provider = _playwright()
    provider._get_page = lambda: _PlaywrightTypePage(actual)

    result = provider.type_text("#q", "typed")

    assert result["success"] is expected_success, result
    assert result["verified"] is expected_success, result
    assert result["content_match"] is expected_success, result


def test_playwright_find_reports_a_count_without_name_error():
    provider = _playwright()
    provider._get_page = lambda: _PlaywrightFindPage(0)

    result = provider.find_text("needle")

    assert result["success"] is True, result
    assert result["count"] == 0, result


def test_playwright_find_verifies_a_positive_match():
    provider = _playwright()
    provider._get_page = lambda: _PlaywrightFindPage(2)

    result = provider.find_text("needle")

    assert result["success"] is True, result
    assert result["count"] == 2, result


@pytest.mark.parametrize(
    ("actual", "expected_success"),
    [("typed", True), ("different", False)],
)
def test_selenium_type_success_follows_the_input_readback(
    actual, expected_success
):
    provider = SeleniumBrowserProvider.__new__(SeleniumBrowserProvider)
    provider._driver = _SeleniumDriver(actual)
    provider._ensure_driver = lambda: None

    result = provider.type_text("#q", "typed")

    assert result["success"] is expected_success, result
    assert result["verified"] is expected_success, result
    assert result["content_match"] is expected_success, result
