"""Item 27B (L7): the internet formatter read "tittle" instead of "title".

internet/parser.py produces {"title": ...} and internet/search.py
returns {"title": ...}; internet/formatter.py looked for the key
"tittle" -- a typo -- so every rendered search result showed the
placeholder "Unknown" as its title, whatever the real title was.

These tests pin:
  * a result carrying "title" renders THAT title,
  * the legacy "tittle" spelling is still tolerated (older stores /
    hand-built payloads),
  * "title" wins when a payload carries both,
  * a payload with neither still gets the "Unknown" placeholder,
  * the parser -> formatter round trip keeps the title.
"""
from __future__ import annotations

from internet.formatter import Formatter
from internet.parser import Parser


def test_a_result_with_title_renders_that_title():
    out = Formatter().format({
        "title": "Python 3.13 release notes",
        "content": "The new interpreter.",
        "url": "https://example.invalid/notes",
    })

    assert "Python 3.13 release notes" in out, (
        f"the formatter dropped the title: {out!r}"
    )
    assert "Unknown" not in out, (
        f"the formatter fell back to the Unknown placeholder: {out!r}"
    )


def test_the_legacy_tittle_spelling_is_still_tolerated():
    out = Formatter().format({
        "tittle": "Legacy title",
        "content": "body",
        "url": "",
    })

    assert "Legacy title" in out, (
        f"the legacy 'tittle' payload lost its title: {out!r}"
    )


def test_title_wins_when_both_spellings_are_present():
    out = Formatter().format({
        "title": "Correct title",
        "tittle": "Stale title",
        "content": "body",
        "url": "",
    })

    assert "Correct title" in out
    assert "Stale title" not in out


def test_a_payload_without_any_title_gets_the_placeholder():
    out = Formatter().format({"content": "body", "url": ""})

    assert "Unknown" in out, (
        f"the placeholder disappeared for a titleless payload: {out!r}"
    )


def test_the_parser_formatter_round_trip_keeps_the_title():
    parsed = Parser().extract({
        "title": "Round trip title",
        "content": "body",
        "url": "https://example.invalid/x",
    })

    out = Formatter().format(parsed)

    assert "Round trip title" in out, (
        f"the parser -> formatter round trip lost the title: {out!r}"
    )
