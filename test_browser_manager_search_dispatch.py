"""Directive 13A (C4): the dead `if "open_url" in self.__dict__` branch.

`BrowserManager.search` guarded an alternative implementation behind

    if "open_url" in self.__dict__:

`self.__dict__` holds INSTANCE attributes. `open_url` is a method on the
class, so it can never appear there: the condition was False for every
instance ever constructed, and the `_dispatch_with_fallback` branch
below it always ran.

It was also the wrong test twice over:

  * the capability it seemed to guard -- "can this manager open a
    URL?" -- is ALWAYS true, because `open_url` is defined on the class
    right there, so a real capability check would have been vacuous;
  * what the condition actually responded to was the presence of an
    unrelated instance attribute. Assigning a stray
    `mgr.open_url = something` was enough to enable it, with no bearing
    on whether any browser existed at all.

It was a FOURTH copy of search logic. Every provider already owns one:
WebBrowserProvider.search (this file), PlaywrightBrowserProvider.search
and SeleniumBrowserProvider.search. It also bypassed
_dispatch_with_fallback, so had it ever run it would have skipped
provider selection AND provider fallback -- strictly worse than the
path actually taken. Deleted rather than repaired.

These tests pin the two things that matter: search goes through provider
dispatch, and the impossible condition cannot come back.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
SRC = BACKEND / "genesis_os" / "browser_manager.py"


def _manager():
    from genesis_os.browser_manager import BrowserManager

    return BrowserManager.__new__(BrowserManager)


class RecordingProvider:
    """A provider that records which method dispatch reached."""

    def __init__(self, name="recording"):
        self.name = name
        self.searches = []
        self.opened = []

    def search(self, query, engine="google"):
        self.searches.append((query, engine))
        return {"success": True, "via": f"{self.name}.search"}

    def open_url(self, url, session_id="default"):
        self.opened.append(url)
        return {"success": True, "via": f"{self.name}.open_url"}


# =====================================================================
# The dead condition cannot come back
# =====================================================================

def _code_only(source: str) -> str:
    """Drop `#` comments.

    Necessary here: the Item 13A comment deliberately QUOTES the old
    condition, so a naive substring search would match the explanation
    of the bug rather than the bug. Checking code only is also the
    honest check -- we care about executable code, not prose.
    """
    import io
    import tokenize

    out = []
    prev_end = (1, 0)
    prev_type = tokenize.INDENT
    try:
        tokens = list(
            tokenize.generate_tokens(io.StringIO(source).readline)
        )
        for token in tokens:
            if token.type == tokenize.COMMENT:
                continue
            out.append(token)
    except tokenize.TokenError:
        return "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    del prev_end, prev_type
    return tokenize.untokenize(out)


def test_the_impossible_condition_is_gone_from_the_source():
    """The regression. Before Item 13A this was executable code."""
    code = _code_only(SRC.read_text(encoding="utf-8-sig"))
    assert "in self.__dict__" not in code, (
        'an `in self.__dict__` guard has returned to browser_manager.py; '
        "it tests instance attributes, so it cannot mean what it looks "
        "like it means"
    )


def test_no_method_name_is_probed_via_instance_dict():
    """Structurally: nothing in this module may test a method's presence
    through `__dict__`."""
    tree = ast.parse(SRC.read_text(encoding="utf-8-sig"))
    offenders = []

    class MethodProbe(ast.NodeVisitor):
        def visit_Compare(self, node):
            if isinstance(node.left, ast.Attribute) and \
                    node.left.attr == "__dict__":
                offenders.append(node.lineno)
            self.generic_visit(node)

    MethodProbe().visit(tree)
    assert not offenders, (
        f"__dict__ membership tests at lines {offenders}; a method name "
        f"can never be an instance attribute"
    )


def test_search_source_contains_no_manual_url_construction():
    """The deleted branch built an engine URL inline. That belongs to the
    providers, not the manager."""
    source = SRC.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "search"
            and getattr(node, "lineno", 0) > 600  # the MANAGER's search
        ):
            body = ast.unparse(node)
            assert "search?q=" not in body, (
                "BrowserManager.search is building a search URL again; "
                "that logic belongs to the providers"
            )
            break


# =====================================================================
# Search really goes through provider dispatch
# =====================================================================

def test_search_reaches_the_provider_search_method():
    """The live path, now the only path."""
    provider = RecordingProvider()
    manager = _manager()
    manager._dispatch_with_fallback = (
        lambda op, fn, session_id: fn(provider)
    )

    result = manager.search("hello world", "bing", session_id="s1")

    assert provider.searches == [("hello world", "bing")], (
        "search did not reach the provider's own search()"
    )
    assert result["via"] == "recording.search", result


def test_search_still_rejects_an_empty_query_without_dispatching():
    provider = RecordingProvider()
    manager = _manager()
    manager._dispatch_with_fallback = (
        lambda op, fn, session_id: fn(provider)
    )

    for bad in ("", "   ", None, 5):
        result = manager.search(bad)
        assert result["success"] is False, (bad, result)

    assert provider.searches == [], "dispatched for an invalid query"


def test_search_does_not_call_open_url_directly():
    """The deleted branch called self.open_url. The manager's own
    open_url must not be reached by search()."""
    provider = RecordingProvider()
    manager = _manager()
    manager._dispatch_with_fallback = (
        lambda op, fn, session_id: fn(provider)
    )
    opened_by_manager = []
    manager.open_url = (
        lambda url, session_id="default": opened_by_manager.append(url)
    )

    manager.search("query", "google")

    assert opened_by_manager == [], (
        "search bypassed provider dispatch and called open_url directly, "
        "which would skip provider selection and fallback"
    )
    assert provider.opened == [], (
        "search bypassed provider dispatch"
    )


def test_a_stray_instance_attribute_no_longer_changes_behaviour():
    """Before the fix, assigning `mgr.open_url` flipped the dead branch
    on. Now it must have no effect at all."""
    def run(with_stray: bool):
        provider = RecordingProvider()
        manager = _manager()
        manager._dispatch_with_fallback = (
            lambda op, fn, session_id: fn(provider)
        )
        if with_stray:
            manager.open_url = lambda url, session_id="default": {
                "success": True, "via": "dead-branch"
            }
        return manager.search("q", "google"), provider

    plain_result, plain_provider = run(False)
    stray_result, stray_provider = run(True)

    assert plain_result == stray_result, (
        "a stray instance attribute changed search behaviour; the guard "
        "is testing attribute presence rather than capability"
    )
    assert plain_provider.searches == stray_provider.searches == [("q", "google")]


# =====================================================================
# The providers keep their own search implementations
# =====================================================================

def test_every_provider_still_implements_search():
    """Deleting the manager's copy must not have removed a provider's."""
    from genesis_os.browser_manager import (
        BrowserProvider,
        WebBrowserProvider,
    )

    for cls in (BrowserProvider, WebBrowserProvider):
        assert "search" in cls.__dict__, (
            f"{cls.__name__} lost its search() implementation"
        )

    for mod_name in ("browser_playwright", "browser_selenium"):
        module = __import__(
            f"genesis_os.{mod_name}", fromlist=["*"]
        )
        found = any(
            isinstance(obj, type)
            and "search" in obj.__dict__
            and obj.__name__.endswith("Provider")
            for obj in vars(module).values()
        )
        assert found, f"{mod_name} lost its provider search()"