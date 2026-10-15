"""Phase 3 maturity: semantic, context-aware, risk-aware selection.

Proves the control-plane gate criteria against the resolver:
enriched descriptors, input/precondition-aware ranking, live
provider-availability signal, risk ordering, description
affinity — with keywords/regex remaining only the upstream hint
path (gate behavior pinned, not weakened).
"""
from types import SimpleNamespace

import time

import pytest

from genesis_os.capabilities import (
    BlastRadius,
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRequirement,
    enrich_descriptor,
)
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.capability_resolver import CapabilityResolver


def _desc(capability_id, operation, supported=(), priority=90,
          description="", risk="low", preconditions=()):
    # blast_radius is a required, reasoned field as of the Step 2
    # classification. These fixtures exist to exercise ranking and
    # threshold logic, not classification, so they carry an explicit
    # test-fixture reason rather than leaving the field blank.
    return CapabilityDescriptor(
        capability_id=capability_id,
        category=CapabilityCategory.GENERAL,
        operation=operation,
        description=description or operation,
        provider="test",
        supported_inputs=frozenset(supported),
        priority=priority,
        risk_level=risk,
        preconditions=tuple(preconditions),
        blast_radius=BlastRadius.REVERSIBLE_LOCAL,
        blast_radius_reason=("Synthetic test fixture; classification is "
                             "not under test in this module."),
    )


class _StubRegistry:
    def __init__(self, descriptors):
        self._descriptors = list(descriptors)

    def all(self):
        return list(self._descriptors)


def _req(operation, inputs=(), description=""):
    return SimpleNamespace(
        capability_id="",
        operation=operation,
        required_inputs=frozenset(inputs),
        optional_inputs=frozenset(),
        description=description,
    )


class TestDescriptorEnrichment:
    def test_destructive_ops_ranked_critical(self):
        registry = CapabilityRegistry()
        assert registry.get("file.delete").risk_level == "critical"
        assert registry.get("folder.delete").risk_level == "critical"
        assert registry.get("cleanup.empty_recycle_bin").risk_level == "critical"

    def test_modifying_ops_ranked_high(self):
        registry = CapabilityRegistry()
        assert registry.get("document.edit").risk_level == "high"
        assert registry.get("file.copy").risk_level == "high"

    def test_read_only_ops_stay_low(self):
        registry = CapabilityRegistry()
        assert registry.get("application.open").risk_level == "low"
        assert registry.get("file.read").risk_level == "low"

    def test_preconditions_seeded(self):
        registry = CapabilityRegistry()
        assert "destination" in registry.get("file.copy").preconditions
        assert "find_text" in registry.get("document.edit").preconditions

    def test_explicit_values_win_over_tables(self):
        explicit = CapabilityDescriptor(
            capability_id="file.delete",
            category=CapabilityCategory.FILESYSTEM,
            operation="file.delete",
            description="custom",
            provider="test",
            risk_level="medium",
            blast_radius=BlastRadius.IRREVERSIBLE_OR_OUTWARD,
            blast_radius_reason="Synthetic fixture mirroring file.delete's real tier.",
        )
        assert enrich_descriptor(explicit).risk_level == "medium"


class TestRankingIsContextAware:
    def test_input_covering_candidate_wins(self):
        a = _desc("a.paste", "paste", supported=("text",), priority=80)
        b = _desc("b.paste", "paste", supported=("other",), priority=80)
        ranked = CapabilityResolver(_StubRegistry([a, b]))._rank_candidates(
            requirement=_req("paste", inputs=("text",)), candidates=[a, b])
        assert ranked[0][0].capability_id == "a.paste"
        assert ranked[0][1] > ranked[1][1]

    def test_safer_candidate_wins_tie(self):
        risky = _desc("x.op", "op", priority=80, risk="critical")
        safe = _desc("y.op", "op", priority=80, risk="low")
        ranked = CapabilityResolver(_StubRegistry([risky, safe]))._rank_candidates(
            requirement=_req("op"), candidates=[risky, safe])
        assert ranked[0][0].capability_id == "y.op"

    def test_missing_precondition_scores_lower(self):
        full = _req("file.copy", inputs=("path", "destination"))
        partial = _req("file.copy", inputs=("path",))
        resolver = CapabilityResolver()
        cap = CapabilityRegistry().get("file.copy")
        score_full = resolver._rank_candidates(
            requirement=full, candidates=[cap])[0][1]
        score_partial = resolver._rank_candidates(
            requirement=partial, candidates=[cap])[0][1]
        assert score_full > score_partial

    def test_description_affinity_breaks_ties(self):
        a = _desc("a.compare", "compare", priority=80,
                  description="Compare two documents for differences")
        b = _desc("b.compare", "compare", priority=80,
                  description="Compare spreadsheet columns numerically")
        ranked = CapabilityResolver(_StubRegistry([a, b]))._rank_candidates(
            requirement=_req("compare", description="differences between documents"),
            candidates=[a, b])
        assert ranked[0][0].capability_id == "a.compare"

    def test_evidence_names_every_component(self):
        cap = CapabilityRegistry().get("document.edit")
        ranked = CapabilityResolver()._rank_candidates(
            requirement=_req("document.edit",
                             inputs=("path", "find_text", "replace_text")),
            candidates=[cap])
        kinds = {e.match_type for e in ranked[0][2]}
        assert {"operation", "input_coverage", "availability",
                "preconditions"} <= kinds

    def test_browser_chain_reports_redundancy(self):
        cap = CapabilityRegistry().get("browser.click")
        ranked = CapabilityResolver()._rank_candidates(
            requirement=_req("click", inputs=("selector",)),
            candidates=[cap])
        kinds = {e.match_type for e in ranked[0][2]}
        assert "provider_redundancy" in kinds


class TestThresholdsIntact:
    def test_unmatched_operation_unsupported(self):
        resolved = CapabilityResolver().resolve(
            _req("no_such_operation_xyz"))
        assert resolved.status.value == "unsupported"

    def test_identical_candidates_ambiguous(self):
        a = _desc("a.same", "sameop", priority=80)
        b = _desc("b.same", "sameop", priority=80)
        resolved = CapabilityResolver(_StubRegistry([a, b])).resolve(
            _req("sameop"))
        assert resolved.status.value == "ambiguous"

    def test_document_and_clipboard_families_resolve(self):
        """These families resolve once their declared preconditions
        are supplied.

        Updated when roadmap task 3 precondition enforcement landed:
        document.edit declares (find_text, replace_text), so a bare
        requirement with no inputs no longer resolves. The test's
        intent -- that these families resolve at all -- is preserved
        by supplying each capability's own declared preconditions,
        which keeps it independent of any hard-coded list."""
        from genesis_os.capability_registry import CapabilityRegistry
        resolver = CapabilityResolver()
        for capability_id in ("document.edit", "document.read",
                              "clipboard.copy", "clipboard.paste"):
            capability = CapabilityRegistry.get(capability_id)
            resolved = resolver.resolve(CapabilityRequirement(
                capability_id=capability_id,
                category=CapabilityCategory.GENERAL,
                operation=capability_id,
                required_inputs=frozenset(capability.preconditions)))
            assert resolved.status.value == "resolved", capability_id
            assert resolved.confidence >= 0.60, capability_id


class TestGateBehaviorPinned:
    """Keywords stay a cost gate; these pins prove it neither
    widened into chatter nor narrowed onto real commands."""

    @pytest.mark.parametrize("text", [
        "stash that file in the archive",
        "get rid of that file",
        "can you open notepad",
        "please delete that file",
        "which files are eating up my disk space",
    ])
    def test_actionable_passes(self, text):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver.looks_actionable(text) is True, text

    @pytest.mark.parametrize("text", [
        "what is the capital of france",
        "hello there friend",
    ])
    def test_conversation_blocked(self, text):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver.looks_actionable(text) is False, text


class TestResolveOperationNeverRaises:
    """Item 1: an unknown operation must be a typed result.

    Previously CapabilityRequirement rejected an empty
    capability_id, so resolve_operation() raised ValueError for
    every unregistered operation and the unguarded callers in
    workflow_decision/genesis aborted the whole request.
    """

    @pytest.mark.parametrize("operation", [
        "",
        "   ",
        None,
        "totally.made_up_op",
        "os.open_app",
        "not a capability at all",
        "file.read.extra",
    ])
    def test_unknown_operation_returns_typed_unsupported(self, operation):
        from genesis_os.capability_resolution import (
            CapabilityResolutionStatus,
        )
        resolution = CapabilityResolver().resolve_operation(operation)
        assert isinstance(
            resolution.status, CapabilityResolutionStatus
        )
        assert resolution.status.value == "unsupported"
        assert resolution.resolved is False
        assert resolution.capability is None
        assert resolution.explanation

    def test_unknown_operation_carries_evidence(self):
        resolution = CapabilityResolver().resolve_operation(
            "totally.made_up_op"
        )
        assert resolution.evidence
        assert resolution.evidence[0].match_type == "unknown_operation"

    def test_unknown_operation_explains_the_unknown_id(self):
        resolution = CapabilityResolver().resolve_operation(
            "totally.made_up_op"
        )
        assert "totally.made_up_op" in resolution.explanation

    def test_registered_operation_still_resolves(self):
        resolution = CapabilityResolver().resolve_operation(
            "file.read", inputs=["path"]
        )
        assert resolution.resolved is True
        assert resolution.capability.capability_id == "file.read"

    def test_decision_engine_does_not_crash_on_unknown_intent(self):
        """The real production call path must survive an
        unregistered intent instead of raising."""
        from agents.workflow_decision import WorkflowDecisionEngine
        engine = WorkflowDecisionEngine(
            capability_resolver=CapabilityResolver()
        )
        decision = engine._resolve_with_capability_control_plane({
            "level": 3,
            "mode": "os",
            "task": "do the thing",
            "intent": "totally.made_up_op",
            "parameters": {},
        })
        # Unresolvable intents are refused, not crashed on, and
        # never silently dressed up as resolved.
        assert decision is None


class TestResolutionMetadataPropagation:
    """Item 1: downstream layers need the FULL verdict."""

    def test_metadata_carries_safety_and_risk_fields(self):
        from genesis_os.capability_resolution import (
            capability_resolution_metadata,
        )
        meta = capability_resolution_metadata(
            CapabilityResolver().resolve_operation("file.delete")
        )
        for key in (
            "status", "capability_id", "capability", "confidence",
            "dangerous", "requires_confirmation", "risk_level",
            "provider", "category", "operation", "explanation",
            "evidence", "alternatives", "alternatives_count",
        ):
            assert key in meta, key
        assert meta["capability_id"] == "file.delete"
        assert meta["dangerous"] is True
        assert meta["requires_confirmation"] is True
        assert meta["risk_level"] == "critical"
        assert meta["provider"]

    def test_metadata_is_json_serialisable(self):
        import json
        from genesis_os.capability_resolution import (
            capability_resolution_metadata,
        )
        meta = capability_resolution_metadata(
            CapabilityResolver().resolve_operation("application.open")
        )
        assert json.loads(json.dumps(meta))["capability_id"] == (
            "application.open"
        )

    def test_none_resolution_is_explicitly_unsupported(self):
        from genesis_os.capability_resolution import (
            capability_resolution_metadata,
        )
        meta = capability_resolution_metadata(None)
        assert meta["status"] == "unsupported"
        assert meta["capability_id"] is None
        assert meta["capability"] is None

    def test_both_call_sites_emit_full_metadata(self):
        """workflow_decision and genesis must not drift."""
        from agents.workflow_decision import WorkflowDecisionEngine
        engine = WorkflowDecisionEngine(
            capability_resolver=CapabilityResolver()
        )
        decision = engine._resolve_with_capability_control_plane({
            "level": 3,
            "mode": "os",
            "task": "delete it",
            "intent": "file.delete",
            "parameters": {},
        })
        assert decision is not None
        meta = decision["parameters"]["_capability_resolution"]
        assert meta["capability_id"] == "file.delete"
        assert meta["dangerous"] is True
        assert meta["risk_level"] == "critical"
        assert meta["provider"]


class TestDefaultResolverWiring:
    """Item 1: the control plane is not opt-in."""

    def test_bare_engine_has_a_real_resolver(self):
        from agents.workflow_decision import WorkflowDecisionEngine
        engine = WorkflowDecisionEngine()
        assert isinstance(
            engine.capability_resolver, CapabilityResolver
        )

    def test_explicit_resolver_is_not_overwritten(self):
        from agents.workflow_decision import WorkflowDecisionEngine
        resolver = CapabilityResolver()
        engine = WorkflowDecisionEngine(capability_resolver=resolver)
        assert engine.capability_resolver is resolver

    def test_bare_engine_resolves_a_real_command(self):
        from agents.workflow_decision import WorkflowDecisionEngine
        engine = WorkflowDecisionEngine()
        decision = engine.decide("delete this file")
        assert decision is not None
        assert decision["level"] == 3
        meta = decision["parameters"]["_capability_resolution"]
        assert meta["status"] == "resolved"
        assert meta["capability_id"] == "file.delete"


class TestLiveProviderHealthSnapshot:
    """Item 1: ranking must read the LIVE registry.

    A throwaway CapabilityProviderRegistry has all-None health, so
    provider-health scoring was silently inert.
    """

    def test_shared_registry_is_a_true_singleton(self):
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        try:
            assert (
                CapabilityProviderRegistry.get_shared()
                is CapabilityProviderRegistry.get_shared()
            )
        finally:
            CapabilityProviderRegistry.reset_shared()

    def test_live_health_is_visible_to_the_resolver(self):
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        try:
            live = CapabilityProviderRegistry.get_shared()
            for entry in live.get_provider_chain("browser.open_url"):
                entry.last_health_check_result = False
                entry.last_health_check_time = time.monotonic()
            resolver = CapabilityResolver()
            resolver.__dict__.pop("_provider_chain_cache", None)
            snapshot = resolver._provider_chain_snapshot()
            assert snapshot["browser.open_url"]["results"] == [
                False, False, False,
            ]
        finally:
            CapabilityProviderRegistry.reset_shared()

    def test_injected_registry_is_honoured(self):
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        live = CapabilityProviderRegistry()
        for entry in live.get_provider_chain("browser.open_url"):
            entry.last_health_check_result = True
            entry.last_health_check_time = time.monotonic()
        resolver = CapabilityResolver(provider_registry=live)
        resolver.__dict__.pop("_provider_chain_cache", None)
        snapshot = resolver._provider_chain_snapshot()
        assert snapshot["browser.open_url"]["results"] == [
            True, True, True,
        ]

    def test_unknown_health_is_reported_not_invented(self):
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        try:
            CapabilityProviderRegistry.reset_shared()
            resolver = CapabilityResolver()
            resolver.__dict__.pop("_provider_chain_cache", None)
            snapshot = resolver._provider_chain_snapshot()
            assert snapshot["browser.open_url"]["results"] == [
                None, None, None,
            ]
        finally:
            CapabilityProviderRegistry.reset_shared()

    def test_unobserved_health_produces_neutral_evidence(self):
        """Unknown health must neither help nor penalise."""
        from genesis_os.capability_resolution import (
            CapabilityResolutionStatus,
        )
        from agents.workflow_decision import WorkflowDecisionEngine
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        try:
            CapabilityProviderRegistry.reset_shared()
            resolver = CapabilityResolver()
            engine = WorkflowDecisionEngine(capability_resolver=resolver)
            decision = engine._resolve_with_capability_control_plane({
                "level": 3,
                "mode": "os",
                "task": "browse",
                "intent": "browser.open_url",
                "parameters": {},
            })
            assert decision is not None
            meta = decision["parameters"]["_capability_resolution"]
            assert meta["status"] == "resolved"
        finally:
            CapabilityProviderRegistry.reset_shared()


class TestSelectionBoundaries:
    """The catalog is only decidable if ambiguous families are
    disambiguated. These pins stop the notes being dropped."""

    def test_ambiguous_families_all_have_boundaries(self):
        from genesis_os.capabilities import SELECTION_BOUNDARIES
        # Members of each family are byte-identical in
        # description, so without a boundary note selection is a
        # coin flip. The twin is not always an "_intel" suffix.
        families = {
            "document.summarize": "document.summarize_intel",
            "document.compare": "document.compare_intel",
            "document.read": "document.read_intel",
            "spreadsheet.read": "spreadsheet.read_intel",
            "spreadsheet.inspect": "spreadsheet.inspect_intel",
            "browser.find": "browser.find_text",
            "application.inspect": (
                "application.inspect_window_content"
            ),
        }
        for base, twin in families.items():
            assert base in SELECTION_BOUNDARIES, base
            assert twin in SELECTION_BOUNDARIES, twin
            assert CapabilityRegistry.exists(base), base
            assert CapabilityRegistry.exists(twin), twin

    def test_boundaries_reference_only_real_capabilities(self):
        from genesis_os.capabilities import SELECTION_BOUNDARIES
        for capability_id in SELECTION_BOUNDARIES:
            assert CapabilityRegistry.exists(capability_id), (
                capability_id
            )

    def test_screenshot_has_exactly_one_owner(self):
        from genesis_os.capabilities import SELECTION_BOUNDARIES
        assert "screen.capture" in SELECTION_BOUNDARIES
        assert not CapabilityRegistry.exists("screen.take")

    def test_catalog_carries_boundary_notes_and_risk(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        catalog = LLMIntentResolver._capability_catalog()
        assert "BOUNDARY:" in catalog
        assert "[critical]" in catalog
        # Grouped by category so the model can narrow by domain.
        assert "[FILESYSTEM]" in catalog
        assert "[DOCUMENT]" in catalog

    def test_catalog_lists_every_registered_capability(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        catalog = LLMIntentResolver._capability_catalog()
        for capability in CapabilityRegistry.all():
            assert capability.capability_id in catalog, (
                capability.capability_id
            )


class TestValidOperationExtraction:
    """Models emit several JSON objects when unsure. Taking the
    first blindly throws away a correct answer over a spelling
    slip, so a real id must win."""

    def test_valid_operation_wins_over_invented_one(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        raw = (
            '{"operation": "screen.take", "target": "x", '
            '"parameters": {}}\n'
            '{"operation": "screen.capture", "target": "screen", '
            '"parameters": {}}'
        )
        parsed = (
            LLMIntentResolver
            ._extract_json_preferring_valid_operation(raw)
        )
        assert parsed["operation"] == "screen.capture"

    def test_single_valid_object_is_returned(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        parsed = (
            LLMIntentResolver
            ._extract_json_preferring_valid_operation(
                '{"operation": "file.delete", "parameters": {}}'
            )
        )
        assert parsed["operation"] == "file.delete"

    def test_explicit_null_is_preserved(self):
        """'This is not a computer request' must never be
        overridden by a stray object later in the answer."""
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver\
            ._extract_json_preferring_valid_operation("null") is None
        assert LLMIntentResolver\
            ._extract_json_preferring_valid_operation(
                'null\n{"operation": "file.delete"}'
            ) is None

    def test_unparseable_output_falls_back(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver\
            ._extract_json_preferring_valid_operation(
                "I cannot help with that."
            ) is None

    def test_fenced_json_is_parsed(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        parsed = (
            LLMIntentResolver
            ._extract_json_preferring_valid_operation(
                '```json\n{"operation": "media.next"}\n```'
            )
        )
        assert parsed["operation"] == "media.next"


class TestSemanticRepair:
    """A correct understanding must not be discarded because the
    model spelled the id wrong."""

    def test_similar_ids_are_real_and_ranked(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        candidates = LLMIntentResolver._similar_capability_ids(
            "screen.take"
        )
        assert candidates
        assert "screen.capture" in candidates
        for capability_id in candidates:
            assert CapabilityRegistry.exists(capability_id)
    def test_repair_accepts_a_corrected_id(self, monkeypatch):
        """Single-stage path: an invented id is corrected once.

        Exercises the single-stage flow explicitly, because
        resolve() now defaults to the two-stage selector and the
        single-stage repair is otherwise unreachable in tests.
        """
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_SINGLE_STAGE", "1")

        calls = []

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                calls.append(prompt)
                if len(calls) == 1:
                    return (
                        '{"operation": "screen.take", "target": "x", '
                        '"parameters": {}}'
                    )
                return '{"operation": "screen.capture", "target": "screen", "parameters": {}}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        out = resolver.resolve("take a screenshot and save it")
        assert out is not None
        assert out["operation"] == "screen.capture"
        # The second call must carry the rejected id and the real
        # near-misses, or the repair is not doing its job.
        assert any("screen.take" in p for p in calls)

    def test_repair_is_not_attempted_for_a_valid_id(self, monkeypatch):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_SINGLE_STAGE", "1")

        calls = []

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                calls.append(prompt)
                return '{"operation": "media.next", "target": "media", "parameters": {}}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        out = resolver.resolve("play the next song")
        assert out["operation"] == "media.next"
        assert len(calls) == 1

    def test_null_answer_is_not_repaired(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                return "null"

        resolver = LLMIntentResolver(ai_engine=_Engine())
        assert resolver.resolve("what is the weather in paris") is None

    def test_invented_id_without_recovery_returns_none(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                return '{"operation": "totally.fake_op", "parameters": {}}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        assert resolver.resolve("do the impossible thing") is None


class TestTwoStageSelector:
    """Two-stage selection exists because the full enriched catalog
    is unaffordable per-request on a CPU-only host: MEASURED with
    qwen2.5:7b on 2 cores at ~10 tok/s, the 5,480-token prompt took
    508s per call. Stage one sends an id-only index, stage two
    sends full descriptors for the shortlist only."""

    def test_shortlist_catalog_is_far_smaller_than_full(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        full = LLMIntentResolver._capability_catalog()
        short = LLMIntentResolver._shortlist_catalog()
        assert len(short) < len(full) / 3, (len(short), len(full))
        # Every capability must still be nameable in stage one.
        for capability in CapabilityRegistry.all():
            assert capability.capability_id in short

    def test_shortlist_has_no_descriptions(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        short = LLMIntentResolver._shortlist_catalog()
        # Stage one is ids only; no boundary notes or risk tags.
        assert "BOUNDARY" not in short
        assert "- " not in short

    def test_detail_catalog_keeps_boundary_notes(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        detail = LLMIntentResolver._detail_catalog([
            "document.summarize_intel", "document.summarize",
        ])
        assert "BOUNDARY:" in detail
        assert "document.summarize_intel" in detail

    def test_detail_catalog_ignores_unknown_ids(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        detail = LLMIntentResolver._detail_catalog([
            "not.a.real.capability", "file.copy",
        ])
        assert "not.a.real.capability" not in detail
        assert "file.copy" in detail

    def test_single_candidate_skips_second_round_trip(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        calls = []

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                calls.append(prompt)
                return '{"candidates": ["screen.capture"]}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        out = resolver.resolve("take a screenshot and save it")
        assert out["operation"] == "screen.capture"
        assert len(calls) == 1, "one shortlist answer needs no second call"

    def test_multiple_candidates_trigger_the_detail_stage(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        calls = []

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                calls.append(prompt)
                if len(calls) == 1:
                    return (
                        '{"candidates": ["volume.down", "volume.up"]}'
                    )
                return (
                    '{"operation": "volume.down", "target": "media", '
                    '"parameters": {}}'
                )

        resolver = LLMIntentResolver(ai_engine=_Engine())
        out = resolver.resolve("turn the sound down a bit")
        assert out["operation"] == "volume.down"
        assert len(calls) == 2
        # The detail stage must actually carry the descriptors.
        assert "volume.down" in calls[1]

    def test_invented_shortlist_ids_are_discarded(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                return '{"candidates": ["screen.take", "file.create_intel"]}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        assert resolver.resolve("take a screenshot") is None

    def test_empty_shortlist_yields_none(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                return '{"candidates": []}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        assert resolver.resolve("do something vague") is None

    def test_declining_shortlist_is_not_an_error(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                return "null"

        resolver = LLMIntentResolver(ai_engine=_Engine())
        assert resolver.resolve("say something nice") is None
    def test_two_stage_is_the_default_path(self, monkeypatch):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.delenv("GENESIS_LLM_SINGLE_STAGE", raising=False)

        class _Engine:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                if "CAPABILITY INDEX" in prompt:
                    return '{"candidates": ["media.play_pause"]}'
                return '{"operation": "media.play_pause", "parameters": {}}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        out = resolver.resolve("what is playing right now")
        assert out["operation"] == "media.play_pause"


class TestDeterministicSelection:
    """Capability selection must be reproducible.

    MEASURED 2026-09-27: with the provider's default sampling the
    same request resolved to media.play_pause on one call and
    gui.read_visible_text on the next, and unbounded output let a
    single request run for 10,859 seconds.
    """

    def test_selection_requests_zero_temperature(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver._SELECTION_TEMPERATURE == 0.0

    def test_selection_caps_output_length(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        cap = LLMIntentResolver._SELECTION_MAX_TOKENS
        assert 0 < cap <= 1024, cap

    def test_generation_kwargs_reach_the_engine(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        seen = []

        class _Engine:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                seen.append(generation_kwargs)
                return '{"candidates": ["file.copy"]}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        resolver.resolve("copy this file to my downloads")
        assert seen, "no engine call was made"
        for kwargs in seen:
            assert kwargs is not None
            assert kwargs["temperature"] == 0.0
            assert kwargs["max_tokens"] > 0

    def test_every_provider_accepts_sampling_controls(self):
        """A provider that rejected the kwargs would raise a
        TypeError inside the resolver and silently look like a
        routing failure."""
        import inspect
        from ai.providers import (
            AnthropicProvider, GroqProvider, OllamaProvider,
            OpenRouterProvider,
        )
        for cls in (OllamaProvider, OpenRouterProvider,
                    GroqProvider, AnthropicProvider):
            params = inspect.signature(cls.generate).parameters
            assert "temperature" in params, cls.__name__
            assert "max_tokens" in params, cls.__name__


class TestRoutingPrecedence:
    """The conversational guard must not discard a correct
    semantic answer. It protects the regex layer only."""

    def test_guard_alone_would_drop_a_capability_question(self):
        """Documents the bug being fixed."""
        from agents.workflow_decision import WorkflowDecisionEngine
        assert WorkflowDecisionEngine\
            ._is_conversational_or_educational(
                "what is playing right now"
            ) is True

    def test_semantic_answer_survives_the_guard(self):
        from agents.workflow_decision import WorkflowDecisionEngine

        engine = WorkflowDecisionEngine()
        semantic = {
            "level": 3, "mode": "os", "task": "what is playing right now",
            "intent": "media.play_pause", "operation": "media.play_pause",
            "target": "media", "confidence": 0.85, "parameters": {},
        }
        engine._try_semantic_intent_resolution = lambda text: semantic
        result = engine._semantic_fallback_for_guarded_text(
            "what is playing right now"
        )
        assert result is not None
        assert result["intent"] == "media.play_pause"

    def test_guard_still_blocks_when_the_model_declines(self):
        from agents.workflow_decision import WorkflowDecisionEngine

        engine = WorkflowDecisionEngine()
        engine._try_semantic_intent_resolution = lambda text: None
        assert engine._semantic_fallback_for_guarded_text(
            "what is the capital of france"
        ) is None

    def test_guard_exception_never_propagates(self):
        from agents.workflow_decision import WorkflowDecisionEngine

        engine = WorkflowDecisionEngine()

        def _boom(text):
            raise RuntimeError("provider exploded")

        engine._try_semantic_intent_resolution = _boom
        assert engine._semantic_fallback_for_guarded_text(
            "what is playing right now"
        ) is None

    def test_knowledge_questions_never_reach_the_model(self):
        """The gate is what keeps general knowledge out; the guard
        alone cannot, so both must hold."""
        from agents.workflow_decision import WorkflowDecisionEngine
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        for text in (
            "what is the capital of france",
            "what is biology",
            "explain what a computer is",
            "write a sentence about Chrome",
            "tell me about Python",
        ):
            assert LLMIntentResolver.looks_actionable(text) is False, text

    def test_capability_questions_do_reach_the_model(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        for text in (
            "what is playing right now",
            "how do these two sheets stack up against each other",
            "what is my disk usage",
        ):
            assert LLMIntentResolver.looks_actionable(text) is True, text


class TestRankingProbes:
    """Step 3 evidence for roadmap task 3, captured as tests.

    Produced by phase3_ranking_probe.py on 2026-09-28; these pin the
    observed behaviour so it cannot drift silently, INCLUDING the
    one probe that failed.
    """

    # --- PROBE 1: preconditions -----------------------------------
    def test_probe_1_preconditions_are_declared(self):
        from genesis_os.capability_registry import CapabilityRegistry
        preconditions = CapabilityRegistry.get(
            "document.transform"
        ).preconditions
        assert "output_format" in preconditions
        assert "output_path" in preconditions

    def test_probe_1_preconditions_are_now_enforced_at_resolution(self):
        """CLOSED GAP. Was pinned as a known failure on 2026-09-28.

        This test originally asserted that document.transform resolves
        despite declaring preconditions, with the explicit intent of
        'pinning the CURRENT behaviour so that fixing it is a
        deliberate, visible change rather than an accident'. This is
        that deliberate change.

        Roadmap task 3 requires capability ranking to take
        preconditions into account. They were metadata used for
        display and a small scoring term, and _resolve_exact
        validated only the inputs the requirement itself declared --
        so an empty required_inputs set meant 'no constraint' and the
        declared preconditions were never checked.

        Enforcement now blocks resolution when a declared
        precondition is unsupplied. Post-closure detail: Phase 3's
        Step 0 decision deliberately measured final3/final4 WITH
        this gap present, so those sealed results stand as historical
        measurements; this fix changes future behaviour only.
        """
        from genesis_os.capabilities import (
            CapabilityCategory, CapabilityRequirement,
        )
        from genesis_os.capability_resolver import CapabilityResolver

        resolver = CapabilityResolver()

        bare = CapabilityRequirement(
            capability_id="document.transform",
            category=CapabilityCategory.DOCUMENT,
            operation="document.transform",
            description="convert this file",
        )
        blocked = resolver.resolve(bare)
        assert blocked.resolved is False
        assert "output_path" in blocked.explanation
        assert "output_format" in blocked.explanation

        satisfied = CapabilityRequirement(
            capability_id="document.transform",
            category=CapabilityCategory.DOCUMENT,
            operation="document.transform",
            description="convert this file",
            required_inputs=frozenset({"output_path", "output_format"}),
        )
        assert resolver.resolve(satisfied).resolved is True

    def test_probe_1_declared_inputs_still_guards_unsupported(self):
        """The input guard that DOES work: requiring an input the
        capability does not support is refused."""
        from genesis_os.capabilities import (
            CapabilityCategory, CapabilityRequirement,
        )
        from genesis_os.capability_resolver import CapabilityResolver

        req = CapabilityRequirement(
            capability_id="file.read",
            category=CapabilityCategory.FILESYSTEM,
            operation="file.read",
            description="read",
            required_inputs=frozenset({"totally_unsupported_input"}),
        )
        resolved = CapabilityResolver().resolve(req)
        assert resolved.resolved is False
        assert resolved.status.value == "unsupported"

    # --- PROBE 2: provider health ---------------------------------
    def test_probe_2_health_changes_ranking_score(self):
        import time as _time
        from types import SimpleNamespace
        from genesis_os.capability_registry import CapabilityRegistry
        from genesis_os.capability_provider_registry import (
            CapabilityProviderRegistry,
        )
        from genesis_os.capability_resolver import CapabilityResolver

        live = CapabilityProviderRegistry.get_shared()
        try:
            def _score(health):
                for entry in live.get_provider_chain(
                    "browser.open_url"
                ):
                    entry.last_health_check_result = health
                    entry.last_health_check_time = _time.monotonic()
                resolver = CapabilityResolver()
                resolver.__dict__.pop(
                    "_provider_chain_cache", None
                )
                req = SimpleNamespace(
                    capability_id="",
                    operation="open url",
                    required_inputs=frozenset(),
                    optional_inputs=frozenset(),
                    description="open a website in the browser",
                )
                ranked = resolver._rank_candidates(
                    requirement=req,
                    candidates=[
                        c for c in CapabilityRegistry.all()
                        if c.capability_id == "browser.open_url"
                    ],
                )
                _, score, evidence = ranked[0]
                health_evidence = [
                    e.to_dict() for e in evidence
                    if e.match_type == "provider_health"
                ]
                return score, health_evidence

            bad_score, bad_ev = _score(False)
            good_score, good_ev = _score(True)
            assert good_score - bad_score > 0.001, (
                good_score, bad_score
            )
            assert bad_ev != good_ev
            assert any(
                e["score"] < 0 for e in bad_ev
            ), bad_ev
            assert any(
                e["score"] > 0 for e in good_ev
            ), good_ev
        finally:
            CapabilityProviderRegistry.reset_shared()

    # --- PROBE 3: risk triggers approval --------------------------
    def test_probe_3_approval_is_required_for_gated_capabilities(self):
        from genesis_os.agent_framework_adapter import (
            APPROVAL_REQUIRED_CAPABILITIES,
            requires_approval_token,
        )
        from genesis_os.capability_registry import CapabilityRegistry

        assert APPROVAL_REQUIRED_CAPABILITIES, "gate must not be empty"
        for capability_id in APPROVAL_REQUIRED_CAPABILITIES:
            assert requires_approval_token(capability_id) is True
            descriptor = CapabilityRegistry.get(capability_id)
            # The gate is a CURATED list, not a pure function of risk
            # tier: application.close is medium risk and still gated,
            # while document.transform is high risk and NOT gated.
            # The invariant that actually holds is that nothing low
            # risk is ever gated.
            assert descriptor.risk_level in {"medium", "high", "critical"}, (
                capability_id, descriptor.risk_level
            )

    def test_probe_3_approval_list_is_curated_not_risk_derived(self):
        """Records the measured asymmetry so nobody later assumes
        the gate == 'risk tier is high or worse'."""
        from genesis_os.agent_framework_adapter import (
            requires_approval_token,
        )
        from genesis_os.capability_registry import CapabilityRegistry

        # Gated despite only being medium risk.
        assert CapabilityRegistry.get(
            "application.close"
        ).risk_level == "medium"
        assert requires_approval_token("application.close") is True
        # High risk but deliberately not gated.
        assert CapabilityRegistry.get(
            "document.transform"
        ).risk_level == "high"
        assert requires_approval_token("document.transform") is False

    def test_probe_3_low_risk_capabilities_are_not_gated(self):
        from genesis_os.agent_framework_adapter import (
            requires_approval_token,
        )
        for capability_id in (
            "media.play_pause", "file.read", "screen.capture",
            "display.brightness_get",
        ):
            assert requires_approval_token(capability_id) is False, (
                capability_id
            )

    def test_probe_3_missing_and_misscoped_tokens_are_rejected(self):
        from genesis_os.agent_framework_adapter import (
            APPROVAL_REQUIRED_CAPABILITIES,
            is_valid_approval_token,
        )
        target = sorted(APPROVAL_REQUIRED_CAPABILITIES)[0]
        assert is_valid_approval_token(None, target) is False
        assert is_valid_approval_token("", target) is False
        assert is_valid_approval_token(
            "HUMAN-APPROVE:file.delete:nonce-123", target
        ) is False, "a token scoped to another capability must fail"
        assert is_valid_approval_token(
            f"HUMAN-APPROVE:{target}:nonce-123", target
        ) is True


class TestNoSentenceSpecificRules:
    """The gate's own wording, enforced as a test.

    An audit on 2026-09-28 found 12 of the 29 few-shot examples in
    _build_prompt were VERBATIM items from the benchmark corpus the
    selector had been tuned against, e.g. "what's eating up my disk
    space" and "how bright is my screen right now". That is
    sentence-specific encoding: the old corpus scored partly because
    its own sentences were in the prompt. All of them are removed and
    this test stops that recurring.
    """

    def test_no_corpus_phrase_appears_as_a_few_shot_example(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        from phase3_benchmark import DEV_ITEMS, build_heldout

        import re as _re
        prompt = LLMIntentResolver._build_prompt(
            "PLACEHOLDER", LLMIntentResolver._capability_catalog()
        )
        examples = set(_re.findall(r'"([^"]{12,200})" ->', prompt))

        phrases = {i["phrase"] for i in build_heldout()}
        phrases |= {d["phrase"] for d in DEV_ITEMS}

        offenders = sorted(examples & phrases)
        assert not offenders, (
            "benchmark phrases are hard-coded as prompt examples: "
            f"{offenders}"
        )

    def test_old_corpus_is_known_to_be_contaminated(self):
        """Locks in a permanent finding about the OLD corpus.

        The 2026-09-26 held-out set was generated by wrapping
        registry DESCRIPTIONS in surface frames, so its items are
        near-verbatim copies of text the selector is shown in its own
        capability catalog. It therefore cannot measure
        generalization and must never be cited as evidence. This test
        exists so that anyone reaching for it sees the reason.
        """
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        from phase3_benchmark import build_heldout

        catalog_norm = " ".join(
            LLMIntentResolver._capability_catalog().lower().split()
        )
        leaked = [
            item["phrase"] for item in build_heldout()
            if " ".join(item["phrase"].lower().split()) in catalog_norm
        ]
        assert leaked, (
            "expected the legacy corpus to overlap the catalog; if this "
            "now fails the corpus was replaced and the contamination "
            "note in the closeout artifact should be updated"
        )

    def test_prompt_examples_are_not_long_sentences_from_the_selector(
        self,
    ):
        """No example may be a full natural request longer than a
        short command; examples should teach ids and boundaries,
        not memorise phrasings."""
        import re
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        prompt = LLMIntentResolver._build_prompt(
            "PLACEHOLDER", LLMIntentResolver._capability_catalog()
        )
        examples = re.findall(r'"([^"]{12,200})" ->', prompt)
        assert examples, "expected few-shot examples to exist"
        for example in examples:
            assert len(example.split()) <= 14, example

    def test_shortlist_prompt_carries_no_examples(self):
        """Stage one must be ids only, so it cannot memorise."""
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert '"' not in LLMIntentResolver._shortlist_catalog()

    def test_gate_lists_contain_no_full_sentences(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        for pattern in (
            LLMIntentResolver._ACTION_HINT_RE.pattern,
            LLMIntentResolver._TECH_NOUN_RE.pattern,
            LLMIntentResolver._STATE_HINT_RE.pattern,
            LLMIntentResolver._SMALL_TALK_RE.pattern,
        ):
            assert "\n" not in pattern
            # A single word per alternative, never a phrase.
            for alternative in pattern.split("|"):
                cleaned = re.sub(r"[^A-Za-z\s]", "", alternative).strip()
                assert len(cleaned.split()) <= 2, alternative

    def test_boundary_notes_describe_capabilities_not_phrases(self):
        from genesis_os.capabilities import SELECTION_BOUNDARIES
        for note in SELECTION_BOUNDARIES.values():
            assert len(note.split()) <= 45, note


import re  # noqa: E402  (used by the tests above)


class TestInFlightSlotStarvation:
    """A timed-out call must not delete every later request.

    MEASURED 2026-09-28: with GENESIS_LLM_INFLIGHT_CAP=1 the batch
    measurement used, a timed-out call left its worker holding the
    only slot. The next request was refused instantly and returned
    None, so the item was lost. Reproduced deterministically with a
    stub engine: slot 1/1 held, next item starved at 0.00s.
    """

    def test_slot_is_released_on_success(self, monkeypatch):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_INFLIGHT_CAP", "1")
        monkeypatch.setenv("GENESIS_LLM_MODES", "local")
        LLMIntentResolver._inflight_calls = 0

        class _Engine:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                return '{"candidates": ["file.copy"]}'

        LLMIntentResolver(ai_engine=_Engine()).resolve(
            "copy this file to my downloads"
        )
        assert LLMIntentResolver._inflight_calls == 0

    def test_slot_is_released_on_exception(self, monkeypatch):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_INFLIGHT_CAP", "1")
        monkeypatch.setenv("GENESIS_LLM_MODES", "local")
        LLMIntentResolver._inflight_calls = 0

        class _Engine:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                raise RuntimeError("provider exploded")

        LLMIntentResolver(ai_engine=_Engine()).resolve("copy this file")
        assert LLMIntentResolver._inflight_calls == 0

    def test_timeout_does_not_starve_the_next_request(self, monkeypatch):
        """The regression itself: fails on the pre-fix code."""
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_INFLIGHT_CAP", "1")
        monkeypatch.setenv("GENESIS_LLM_MODES", "local")
        monkeypatch.setattr(
            LLMIntentResolver, "_LLM_CALL_TIMEOUT", 0.5
        )
        # Shrink the hold cap so the test does not sleep 240s.
        monkeypatch.setattr(
            LLMIntentResolver, "_INFLIGHT_HOLD_SECONDS", 1.0
        )
        LLMIntentResolver._inflight_calls = 0

        class _Slow:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                import time as _t
                _t.sleep(30)
                return '{"candidates": ["file.copy"]}'

        class _Fast:
            def generate_response(self, prompt, mode=None,
                                  generation_kwargs=None):
                return '{"candidates": ["file.copy"]}'

        # First call times out and leaves an orphan holding the slot.
        LLMIntentResolver(ai_engine=_Slow()).resolve(
            "copy this file to my downloads"
        )
        # The next request must still be served.
        import time as _t
        _t.sleep(1.5)                     # let the watchdog fire
        out = LLMIntentResolver(ai_engine=_Fast()).resolve(
            "copy this file to my downloads"
        )
        assert out is not None, (
            "next request was starved by the abandoned worker"
        )
        assert out["operation"] == "file.copy"
        LLMIntentResolver._inflight_calls = 0

    def test_watchdog_cannot_exceed_the_cap(self, monkeypatch):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        monkeypatch.setenv("GENESIS_LLM_INFLIGHT_CAP", "2")
        assert LLMIntentResolver._inflight_cap() == 2
        # Releasing more times than acquired must not go negative.
        LLMIntentResolver._inflight_calls = 0
        for _ in range(5):
            LLMIntentResolver._release_inflight_slot()
        assert LLMIntentResolver._inflight_calls == 0


class TestOllamaNativeEndpoint:
    """Long prompts must not die on the compatibility shim.

    MEASURED 2026-09-28: a 772-token capability-selection prompt
    that the model answers CORRECTLY in 209s via /api/generate was
    killed at ~188s by the OpenAI-compatibility layer with
    'Request timed out', and the resolver reported that as "the model
    declined" for every item.
    """

    def test_native_root_strips_v1(self):
        from ai.providers import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider._base_url = "http://localhost:11434/v1"
        assert provider._native_root == "http://localhost:11434"

    def test_native_root_tolerates_trailing_slash(self):
        from ai.providers import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider._base_url = "http://localhost:11434/v1/"
        assert provider._native_root == "http://localhost:11434"

    def test_capability_prompt_exceeds_the_native_threshold(self):
        from ai.providers import OllamaProvider
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        prompt = LLMIntentResolver._build_prompt(
            "what is playing right now",
            LLMIntentResolver._shortlist_catalog(),
        )
        assert len(prompt) > OllamaProvider._NATIVE_MIN_PROMPT_CHARS

    def test_short_prompts_stay_on_the_compatibility_path(self):
        from ai.providers import OllamaProvider
        assert len("hello") < OllamaProvider._NATIVE_MIN_PROMPT_CHARS

    def test_generate_falls_back_to_the_shim_on_native_failure(
        self, monkeypatch
    ):
        """A native failure must not break ordinary generation."""
        from ai.providers import OllamaProvider

        provider = OllamaProvider.__new__(OllamaProvider)
        provider._model = "test-model"
        provider._available = True
        provider._base_url = "http://localhost:11434/v1"

        def _boom(*a, **k):
            raise RuntimeError("native endpoint down")

        monkeypatch.setattr(provider, "_generate_native", _boom)

        calls = {}

        class _Completions:
            def create(self, **kwargs):
                calls.update(kwargs)

                class _Msg:
                    content = "from the shim"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        provider._client = _Client()

        out = provider.generate("x" * 5000)
        assert out == "from the shim"
        assert calls["model"] == "test-model"


class TestInFlightSlotStarvationPlaceholder:
    """placeholder"""


class TestProviderCallBounding:
    """Latency regressions are silent correctness problems for an
    interactive CLI, so the bounds are pinned."""

    def test_budgets_are_bounded(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver._LLM_CALL_TIMEOUT <= 15.0
        assert LLMIntentResolver._RESOLVE_TOTAL_BUDGET <= 30.0
        assert LLMIntentResolver._MAX_INFLIGHT_CALLS >= 1

    def test_inflight_slots_are_bounded_and_released(self):
        from genesis_os.llm_intent_resolver import LLMIntentResolver
        assert LLMIntentResolver._acquire_inflight_slot() is True
        try:
            for _ in range(
                LLMIntentResolver._MAX_INFLIGHT_CALLS
            ):
                LLMIntentResolver._acquire_inflight_slot()
            # Cap reached: further calls must be refused rather
            # than making provider saturation worse.
            assert (
                LLMIntentResolver._acquire_inflight_slot() is False
            )
        finally:
            for _ in range(
                LLMIntentResolver._MAX_INFLIGHT_CALLS + 1
            ):
                LLMIntentResolver._release_inflight_slot()

    def test_slow_provider_is_bounded_by_the_total_budget(self):
        import time as _time
        from genesis_os.llm_intent_resolver import LLMIntentResolver

        class _Engine:
            def generate_response(self, prompt, mode=None, generation_kwargs=None):
                _time.sleep(30)
                return '{"operation": "file.delete"}'

        resolver = LLMIntentResolver(ai_engine=_Engine())
        started = _time.monotonic()
        resolver.resolve("get rid of this file for me")
        elapsed = _time.monotonic() - started
        assert elapsed < 40, elapsed

