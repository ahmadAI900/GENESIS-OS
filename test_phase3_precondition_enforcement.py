"""
Phase 3 — roadmap task 3: capability ranking with PRECONDITIONS.

THE GAP THIS CLOSES
-------------------
`preconditions` were declared on capability descriptors but never
enforced. They were read in exactly one place,
`CapabilityResolver._rank_candidates`, where they contributed a score
nudge of +0.03 per met and -0.05 per unmet — and that entire block sat
behind `if preconditions and declared_inputs:`, so a requirement that
declared NO inputs skipped the check completely.

The observable consequence: `document.transform` declares
("output_path", "output_format") yet resolved successfully while
supplying neither. Phase 3's Step 0 decision deliberately measured
with that gap present ("measure WITH the gap, fix afterward"); this is
that "afterward".

KIND ANALYSIS (why one mechanism suffices)
------------------------------------------
All 17 precondition-bearing capabilities and all 23 preconditions were
enumerated. Every single precondition is a REQUIRED INPUT name, and
every one is also that capability's declared supported input. There is
no prior-state precondition and no target-existence precondition
anywhere in the registry, so one generic input-presence mechanism
covers the registry and no per-capability mapping exists.

STATUS SHAPE
------------
Unmet preconditions return UNAVAILABLE, not a new status. The
capability exists and is enabled; it cannot be used *as specified*
until the missing inputs exist. That reuses the existing result
vocabulary, and the explanation names exactly which inputs are
missing, so the cause stays distinguishable from provider
unavailability.

NOTHING ELSE IN THIS ITEM WAS TOUCHED: no arbitration trigger, no
grounding logic, no GroundingResult, no sealed corpus.
"""

import json
import re
from pathlib import Path

import pytest

from genesis_os.capabilities import CapabilityRequirement
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.capability_resolution import CapabilityResolutionStatus
from genesis_os.capability_resolver import CapabilityResolver

BACKEND = Path(__file__).resolve().parent


def _requirement(capability, inputs=(), optional=()):
    """A requirement naming a real capability, with chosen inputs."""
    return CapabilityRequirement(
        capability_id=capability.capability_id,
        category=capability.category,
        operation=capability.operation,
        description=f"synthetic requirement for {capability.capability_id}",
        required_inputs=frozenset(inputs),
        optional_inputs=frozenset(optional),
    )


PRECONDITION_CAPABILITIES = sorted(
    (
        capability
        for capability in CapabilityRegistry.all()
        if getattr(capability, "preconditions", None)
    ),
    key=lambda capability: capability.capability_id,
)

NO_PRECONDITION_CAPABILITIES = sorted(
    (
        capability
        for capability in CapabilityRegistry.all()
        if not getattr(capability, "preconditions", None)
        # The no-op guarantee is about AVAILABLE capabilities. An
        # UNAVAILABLE one must NOT resolve as RESOLVED with no inputs,
        # so including it here would assert the opposite of correct
        # behaviour. system.shutdown / system.restart are registered
        # UNAVAILABLE (no OSManager implementation) and are excluded
        # for that reason.
        and getattr(capability, "availability", None) is not None
        and capability.availability.value == "available"
    ),
    key=lambda capability: capability.capability_id,
)


# =========================================================
# REGISTRY-WIDE PREMISES
# =========================================================

def test_registry_has_precondition_bearing_capabilities():
    assert len(PRECONDITION_CAPABILITIES) == 17
    assert len(NO_PRECONDITION_CAPABILITIES) == 124


def test_every_precondition_is_a_required_input_name():
    """This is what licenses ONE generic mechanism. If a future
    capability declares a prior-state precondition that is not an
    input name, this test fails and the enforcement below is no
    longer sufficient — which is the signal to handle it
    explicitly rather than let it pass silently."""
    all_inputs = set()
    for capability in CapabilityRegistry.all():
        all_inputs |= set(capability.supported_inputs or ())
    non_input = [
        (capability.capability_id, name)
        for capability in PRECONDITION_CAPABILITIES
        for name in capability.preconditions
        if name not in all_inputs
    ]
    assert non_input == []


# =========================================================
# ONE TEST PER PRECONDITION-BEARING CAPABILITY
# =========================================================

@pytest.mark.parametrize(
    "capability",
    PRECONDITION_CAPABILITIES,
    ids=lambda c: c.capability_id,
)
def test_unmet_preconditions_block_resolution(capability):
    """No inputs supplied -> every declared precondition is unmet."""
    result = CapabilityResolver().resolve(_requirement(capability))

    assert result.resolved is False, capability.capability_id
    assert result.status is CapabilityResolutionStatus.UNAVAILABLE
    assert result.confidence == 0.0
    for name in capability.preconditions:
        assert name in result.explanation, name
    match_types = [item.match_type for item in result.evidence]
    assert "preconditions_unmet" in match_types


@pytest.mark.parametrize(
    "capability",
    PRECONDITION_CAPABILITIES,
    ids=lambda c: c.capability_id,
)
def test_met_preconditions_resolve_normally(capability):
    """Supplying every declared precondition resolves as before."""
    result = CapabilityResolver().resolve(
        _requirement(capability, inputs=capability.preconditions)
    )
    assert result.resolved is True, capability.capability_id
    assert result.status is CapabilityResolutionStatus.RESOLVED


@pytest.mark.parametrize(
    "capability",
    PRECONDITION_CAPABILITIES,
    ids=lambda c: c.capability_id,
)
def test_partial_preconditions_still_block(capability):
    """One missing precondition is enough to block; partial
    satisfaction must not resolve."""
    if len(capability.preconditions) < 2:
        pytest.skip("single-precondition capability")
    partial = tuple(capability.preconditions[:-1])
    result = CapabilityResolver().resolve(
        _requirement(capability, inputs=partial)
    )
    assert result.resolved is False, capability.capability_id
    missing = capability.preconditions[-1]
    assert missing in result.explanation


def test_precondition_may_be_satisfied_from_context():
    """A precondition declared optional counts as context-resolvable,
    so a capability whose input arrives from context still
    resolves."""
    result = CapabilityResolver().resolve(
        _requirement(
            CapabilityRegistry.get("document.transform"),
            optional={"output_path", "output_format"},
        )
    )
    assert result.resolved is True


# =========================================================
# NO-OP GUARANTEE
# =========================================================

@pytest.mark.parametrize(
    "capability",
    NO_PRECONDITION_CAPABILITIES,
    ids=lambda c: c.capability_id,
)
def test_capabilities_without_preconditions_are_unaffected(capability):
    """Strict no-op: resolving with NO inputs at all behaves exactly
    as it did before enforcement existed."""
    result = CapabilityResolver().resolve(_requirement(capability))
    assert result.resolved is True, capability.capability_id
    assert result.status is CapabilityResolutionStatus.RESOLVED
    assert result.confidence == 1.0
    match_types = [item.match_type for item in result.evidence]
    assert "preconditions_unmet" not in match_types


def test_no_op_also_holds_when_inputs_are_supplied():
    """Supplying a REAL supported input must not change anything.

    Note: supplying an input the capability does not declare is a
    pre-existing, separate validation path that yields UNSUPPORTED
    with the explanation "does not support all required inputs".
    That behaviour is unrelated to preconditions and is left
    untouched.
    """
    for capability in NO_PRECONDITION_CAPABILITIES:
        inputs = sorted(capability.supported_inputs or ())
        if not inputs:
            continue
        result = CapabilityResolver().resolve(
            _requirement(capability, inputs=inputs[:1])
        )
        assert result.resolved is True, capability.capability_id


# =========================================================
# document.transform — THE ORIGINAL MEASURED-WITH-GAP CASE
# =========================================================

def test_document_transform_without_inputs_is_blocked():
    """Phase 3 Step 0 measured this case WITH the gap: it resolved.
    Post-fix it correctly does not."""
    result = CapabilityResolver().resolve(
        _requirement(CapabilityRegistry.get("document.transform"))
    )
    assert result.resolved is False
    assert "output_path" in result.explanation
    assert "output_format" in result.explanation


def test_document_transform_with_both_inputs_resolves():
    result = CapabilityResolver().resolve(
        _requirement(
            CapabilityRegistry.get("document.transform"),
            inputs={"output_path", "output_format"},
        )
    )
    assert result.resolved is True


def test_document_transform_with_only_output_path_is_blocked():
    result = CapabilityResolver().resolve(
        _requirement(
            CapabilityRegistry.get("document.transform"),
            inputs={"output_path"},
        )
    )
    assert result.resolved is False
    assert "output_format" in result.explanation


# =========================================================
# CORPUS INTEGRITY — sealed measurements are historical
# =========================================================

def test_no_sealed_corpus_phrase_in_this_test_or_resolver():
    """No benchmark phrase may be encoded in the enforcement or in
    these tests. Enforced mechanically."""
    sources = [
        BACKEND / "test_phase3_precondition_enforcement.py",
        BACKEND / "genesis_os" / "capability_resolver.py",
    ]
    raw = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in sources
    )

    def norm(text):
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    collapsed = norm(raw)
    checked = 0
    for sealed_name in ("phase3_v3_SEALED.json",
                        "phase3_v4_SEALED.json"):
        sealed_file = BACKEND / sealed_name
        if not sealed_file.exists():
            continue
        sealed = json.loads(sealed_file.read_text(encoding="utf-8"))
        for split in ("dev3", "final3", "dev4", "final4"):
            for item in sealed.get(split, []):
                phrase = item.get("phrase")
                if not phrase:
                    continue
                checked += 1
                assert norm(phrase) not in collapsed, (
                    f"benchmark phrase reused verbatim: {phrase!r}"
                )
    assert checked > 0