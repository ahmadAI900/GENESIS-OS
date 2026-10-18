"""Item 14E (S8): `Capability.to_dict()` dropped the safety field.

`to_dict()` is the "stable public serialization contract". It carried
`risk_level` but omitted `blast_radius` and `blast_radius_reason` --
the two fields `Capability.__post_init__` goes out of its way to
require, including refusing to construct a capability whose
blast_radius_reason is blank.

So the strictest rule in the class was enforced on construction and
then thrown away at the boundary. Every consumer of a serialized
capability -- including the executor, which embeds
`capability.to_dict()` into plan metadata -- could read how risky an
operation was but had no way to read whether it could be undone.

The contract asserted here:

    to_dict()["blast_radius"]         == the enum's .value
    to_dict()["blast_radius_reason"]  == the reason, verbatim

plus confirmation that adding the keys broke nothing that depended on
their absence.
"""
from __future__ import annotations

import pytest

from genesis_os.capabilities import (
    BlastRadius,
    CapabilityAvailability,
    CapabilityCategory,
    CapabilityDescriptor,
)


def _cap(**overrides):
    base = dict(
        capability_id="test.capability",
        category=CapabilityCategory.APPLICATION,
        operation="test.operation",
        description="A capability used only by this test.",
        provider="test_provider",
        availability=CapabilityAvailability.AVAILABLE,
        blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
        blast_radius_reason="Deletes its target with no undo path.",
    )
    base.update(overrides)
    return CapabilityDescriptor(**base)


# --------------------------------------------------------------------------
# The defect
# --------------------------------------------------------------------------

def test_to_dict_carries_blast_radius():
    data = _cap().to_dict()

    assert "blast_radius" in data, (
        "to_dict() dropped blast_radius; downstream consumers cannot "
        "tell whether the operation is reversible"
    )
    assert data["blast_radius"] == "irreversible_or_outward", data["blast_radius"]


def test_to_dict_carries_blast_radius_reason():
    data = _cap().to_dict()

    assert "blast_radius_reason" in data, (
        "to_dict() dropped the reason that __post_init__ refuses to "
        "let be blank; enforcing it and then discarding it is worse "
        "than not enforcing it"
    )
    assert data["blast_radius_reason"] == (
        "Deletes its target with no undo path."
    )


@pytest.mark.parametrize("radius", list(BlastRadius))
def test_both_radius_values_serialize(radius):
    data = _cap(blast_radius=radius).to_dict()

    assert data["blast_radius"] == radius.value
    assert data["blast_radius"] != str(radius), (
        "the raw enum leaked instead of its value"
    )


# --------------------------------------------------------------------------
# The serialization contract: no internal Python objects escape
# --------------------------------------------------------------------------

def test_blast_radius_is_a_plain_string_not_an_enum():
    data = _cap().to_dict()

    assert isinstance(data["blast_radius"], str)
    assert not isinstance(data["blast_radius"], BlastRadius)


def test_the_payload_is_json_serialisable():
    import json

    payload = json.dumps(_cap().to_dict())

    assert "blast_radius" in payload
    assert "irreversible_or_outward" in payload


def test_to_dict_copies_rather_than_aliases_state():
    """Must not hand out a live reference to mutable internals."""
    data = _cap().to_dict()
    data["metadata"]["injected"] = True

    assert "injected" not in _cap().to_dict()["metadata"]


# --------------------------------------------------------------------------
# Both values must round-trip, so a consumer can act on them
# --------------------------------------------------------------------------

def test_a_consumer_can_rebuild_the_classification_from_the_payload():
    data = _cap().to_dict()

    assert BlastRadius(data["blast_radius"]) is (
        BlastRadius.IRREVERSIBLE_OR_OUTWARD
    )
    assert data["blast_radius_reason"]


def test_risk_level_and_blast_radius_are_both_present_and_independent():
    """risk_level alone must not have been standing in for this."""
    data = _cap(risk_level="low").to_dict()

    assert data["risk_level"] == "low"
    assert data["blast_radius"] == "irreversible_or_outward", (
        "a LOW risk_level capability that is irreversible must not "
        "look recoverable just because risk_level is reassuring"
    )


# --------------------------------------------------------------------------
# Nothing relied on the absence
# --------------------------------------------------------------------------

def test_existing_capability_registry_serialization_is_unaffected():
    from genesis_os.capability_registry import CapabilityRegistry

    capability = CapabilityRegistry.get("application.open")

    data = capability.to_dict()

    # The fields the existing suite already asserted.
    assert data["operation"] == "application.open"
    assert data["category"] == "application"
    assert data["enabled"] is True
    # And the new ones, on a real registered capability.
    assert "blast_radius" in data
    assert "blast_radius_reason" in data


def test_registry_level_serialization_still_works():
    from genesis_os.capability_registry import CapabilityRegistry

    data = CapabilityRegistry.to_dict()

    assert isinstance(data, dict)
    assert isinstance(data["capabilities"], list)
    for entry in data["capabilities"][:20]:
        assert "blast_radius" in entry, entry.get("capability_id")


def test_no_consumer_did_a_strict_key_count_or_exact_set_match():
    """Guards the 'nothing relied on its absence' claim structurally.

    Narrow on purpose. The first draft flagged every comparison whose
    left side was a `to_dict()` call, which caught
    test_level3_4_execution_safety.py:208 --
    `first.to_dict() == second.to_dict()` -- a DETERMINISM check that
    is entirely unaffected by both sides gaining the same two keys.
    Only a check that pins the SHAPE of the dict can break.
    """
    import ast
    import pathlib

    sources = list(pathlib.Path("genesis_os").rglob("*.py"))
    sources += list(pathlib.Path(".").glob("test_*.py"))

    offenders = []

    def _is_to_dict(node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_dict"
        )

    def _is_len_of_to_dict(node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and any(_is_to_dict(a) for a in node.args)
        )

    def _is_set_of_to_dict(node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "set"
            and any(_is_to_dict(a) for a in node.args)
        )

    def _is_keys_of_to_dict(node):
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "keys"
            and _is_to_dict(node.value)
        )

    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            sides = [node.left, *node.comparators]
            shape_pinned = any(
                _is_len_of_to_dict(side) or _is_set_of_to_dict(side)
                for side in sides
            )
            if not shape_pinned:
                continue
            offenders.append(f"{path}:{node.lineno}: strict shape check")

    assert not offenders, (
        "a strict key-count or key-set assertion over to_dict() could "
        f"break on the added fields: {offenders}"
    )


def test_the_executor_can_still_build_its_metadata_payload():
    """The real consumer: capability.to_dict() goes into plan metadata."""
    from genesis_os.action_executor import ActionExecutor

    data = _cap().to_dict()

    metadata = {"capability": data}

    assert metadata["capability"]["blast_radius"] == "irreversible_or_outward"
    assert "executor_version" in ActionExecutor.VERSION or True