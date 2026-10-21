"""Item 26F (L13): fact key normalization mismatch -- _derive_key used
hyphens while upsert_fact/get_fact used underscores.

``_derive_key("I moved to Berlin")`` returned ``"moved-to-berlin"``
(hyphen-joined). ``upsert_fact`` normalized labels with
``replace(" ", "_")`` -- hyphens survive -- so the fact was STORED
under the hyphen key. ``get_fact("moved to berlin")`` normalized its
label to ``"moved_to_berlin"`` and could never match: upsert then get
with the same meaning returned nothing. Every fact entering memory
through the derive path was unreachable by the label-based read path.

The fix introduces ONE canonical normalization -- stripped, lowercased,
spaces AND legacy hyphens folded to underscores -- used by upsert,
get and the derive join. Folding hyphens on the READ side too means
OLD stores whose keys are hyphenated remain readable (backward
compatible), and upsert matches them in place instead of duplicating.
"""
from __future__ import annotations

import json

from memory.long_term_memory import LongTermMemory


def _ltm(tmp_path) -> LongTermMemory:
    return LongTermMemory(
        storage_path=str(tmp_path / "long_term_memory.json")
    )


LEGACY_FACT = {
    "key": "prefer-dark-mode",
    "value": "dark",
    "category": "preference",
    "confidence": 0.9,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "last_seen": "2026-01-01T00:00:00",
    "history": [],
}


def _write_legacy_store(tmp_path) -> None:
    (tmp_path / "long_term_memory.json").write_text(
        json.dumps({"version": LongTermMemory.VERSION, "facts": [LEGACY_FACT]}),
        encoding="utf-8",
    )


def test_derived_key_path_round_trips(tmp_path):
    ltm = _ltm(tmp_path)
    key = LongTermMemory._derive_key("I moved to Berlin")
    result = ltm.upsert_fact(key, "Berlin")
    assert result is not None, "upsert rejected the derived key"

    fact = ltm.get_fact("moved berlin")
    assert fact is not None, (
        "the _derive_key path stored a key the label-based get_fact "
        "can never find (hyphen vs underscore normalization)"
    )
    assert fact["value"] == "Berlin"


def test_upsert_then_get_with_same_label(tmp_path):
    ltm = _ltm(tmp_path)
    result = ltm.upsert_fact("favorite color", "blue")
    assert result is not None and result["action"] == "created"
    fact = ltm.get_fact("favorite color")
    assert fact is not None and fact["value"] == "blue"


def test_legacy_hyphen_key_is_still_readable(tmp_path):
    _write_legacy_store(tmp_path)
    ltm = _ltm(tmp_path)

    fact = ltm.get_fact("prefer dark mode")
    assert fact is not None, (
        "a legacy hyphen-keyed fact became unreadable after the "
        "normalization change"
    )
    assert fact["value"] == "dark"


def test_upsert_updates_legacy_fact_in_place_without_duplicating(tmp_path):
    _write_legacy_store(tmp_path)
    ltm = _ltm(tmp_path)

    result = ltm.upsert_fact("prefer dark mode", "light")
    assert result is not None
    assert result["action"] == "updated", result

    facts = ltm.all_facts()
    assert len(facts) == 1, (
        f"updating a legacy hyphen fact created a duplicate: {facts!r}"
    )
    assert facts[0]["value"] == "light"


def test_derive_key_uses_canonical_underscores():
    assert (
        LongTermMemory._derive_key("I moved to Berlin")
        == "moved_berlin"
    )
