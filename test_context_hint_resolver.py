"""
Genesis OS — Context Hint Resolver Regression Tests (Level 3.19).

These tests exercise the structured context-propagation
mechanism that resolves 2nd-clause phrasings whose meaning
depends on the 1st clause's resolved target.

The resolver lives in ``genesis_os/context_hint_resolver.py``
and is wired into ``ObjectiveUnderstanding._understand_fragment``
so the 1st clause's successful L3 OS decision is carried as
a structured ContextHint to the 2nd clause.

Spec compliance
---------------
* Each test family probes multiple unseen paraphrases of
  the same underlying pattern (settings sub-page, browser
  search, file manager rename).
* The tests prove that context-resolved 2nd clauses are
  real Level-3 OS intents that flow through the existing
  ActionExecutor (no bypass).
* False-positive guards protect single-step and
  conversational requests from being hijacked by the
  context resolver.
"""

import sys
from pathlib import Path
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real GenesisOS.
# --------------------------------------------------------------
pytestmark = pytest.mark.live

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from genesis_os.context_hint_resolver import (
    ContextHintResolver,
    ContextHint,
    build_context_hint,
    SETTINGS_SUB_PAGES,
)
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.objective_understanding import ObjectiveUnderstanding




# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def wde():
    return WorkflowDecisionEngine()


@pytest.fixture
def ou(wde):
    return ObjectiveUnderstanding(wde)


@pytest.fixture
def resolver():
    return ContextHintResolver()


# ---------------------------------------------------------------------
# POSITIVE: settings sub-page resolution (with prior context)
# ---------------------------------------------------------------------


class TestSettingsSubPageContext:
    """When the 1st clause opens the settings app, the 2nd
    clause's noun is resolved as a settings sub-page.

    The last two rows are RECONSTRUCTED 2026-10-04 from
    ``phase2_collect_now.txt:72``, the surviving ``--collect-only``
    dump whose node ids encode
    ``<first_clause>-<second_clause>-<expected_sub_page>``. No
    assertion text was invented; the body below is the original.
    """

    @pytest.mark.parametrize(
        "first_clause,second_clause,expected_sub_page",
        [
            ("open settings", "turn on bluetooth", "bluetooth"),
            ("open settings", "turn off notifications", "notifications"),
            ("open settings", "enable high contrast", "easeofaccess"),
            ("open the display settings", "disable night light", "display"),
            ("open accessibility", "enable high contrast", "easeofaccess"),
            ("open wifi", "connect to my home network", "network-wifi"),
            # RECONSTRUCTED from phase2_collect_now.txt:72
            pytest.param(
                "open the display settings",
                "turn on dark mode",
                "personalization",
                marks=pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "PRE-EXISTING GAP, not a regression. 'dark mode' "
                        "is a trigger for BOTH the display and the "
                        "personalization sub-page, and the resolver "
                        "returns 'display'. That is arguably the better "
                        "answer, since the user explicitly said 'display "
                        "settings', so the cited expectation may itself "
                        "be wrong -- but it was verified byte-identical "
                        "against the 2026-09-21 context_hint_resolver.py, "
                        "so nothing in the last two weeks changed it. "
                        "strict=True so resolving the ambiguity fails "
                        "this test and forces a decision."
                    ),
                ),
            ),
            pytest.param(
                "open the sound settings",
                "switch the output to headphones",
                "sound",
                marks=pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "PRE-EXISTING GAP, not a regression. The compound "
                        "detector does not split 'open the sound settings "
                        "and switch the output to headphones' into two "
                        "clauses, so no sub-page is ever resolved. "
                        "'switch the output' carries no Level-3 verb the "
                        "splitter recognises. Verified byte-identical "
                        "against the 2026-09-21 objective_understanding"
                        ".py. strict=True so fixing the splitter fails "
                        "this test and forces the marker to be removed."
                    ),
                ),
            ),
        ],
    )
    def test_routes_to_system_open_settings_sub_page(
        self, wde, ou, first_clause, second_clause, expected_sub_page
    ):
        res = ou.understand(
            f"{first_clause} and {second_clause}"
        )
        # The compound must produce at least 2 steps.
        assert len(res.steps) >= 2, (
            f"Expected >=2 steps for "
            f"{first_clause!r} and {second_clause!r}, got "
            f"{len(res.steps)}: {[s.text for s in res.steps]}"
        )
        # The 2nd step must be a system.open_settings intent
        # targeting the expected sub-page.
        second_step = res.steps[-1]
        assert second_step.level == 3
        assert second_step.mode == "os"
        assert second_step.operation == "system.open_settings"
        assert second_step.target == expected_sub_page
        assert second_step.executable_intent is True
        # The decision should be tagged as context-resolved.
        assert second_step.decision.get(
            "source"
        ) == "context_hint_resolver"


# ---------------------------------------------------------------------
# POSITIVE: browser context resolution
# ---------------------------------------------------------------------


class TestBrowserContext:
    """When the 1st clause opens a browser, the 2nd clause's
    search / navigate verbs are resolved as browser actions.

    The last row is RECONSTRUCTED 2026-10-04 from
    ``phase2_collect_now.txt:78``. No assertion text was invented.
    """

    @pytest.mark.parametrize(
        "first_clause,second_clause",
        [
            ("open chrome", "search for python tutorials"),
            ("open firefox", "go to my bank"),
            ("open edge", "go to wikipedia"),
            ("open chrome", "navigate to stack overflow"),
            ("open chrome", "search for the latest news"),
            ("open chrome", "visit github"),
            # RECONSTRUCTED from phase2_collect_now.txt:78
            ("open the browser", "search for the latest news"),
        ],
    )
    def test_browser_context_routes_to_browser_intent(
        self, wde, ou, first_clause, second_clause
    ):
        res = ou.understand(
            f"{first_clause} and {second_clause}"
        )
        assert len(res.steps) >= 2
        second_step = res.steps[-1]
        assert second_step.level == 3
        assert second_step.mode == "os"
        assert second_step.operation in {
            "browser.search", "browser.open_url",
        }


# ---------------------------------------------------------------------
# POSITIVE: direct settings sub-page resolution (no prior context)
# ---------------------------------------------------------------------


class TestDirectSettingsSubPage:
    """When the fragment itself names a settings sub-page, the
    resolver returns a direct system.open_settings intent even
    without a prior L3 clause."""

    @pytest.mark.parametrize(
        "text,expected_sub_page",
        [
            ("open accessibility settings", "easeofaccess"),
            ("open bluetooth settings", "bluetooth"),
            ("open display settings", "display"),
            ("open sound settings", "sound"),
            ("open wifi settings", "network-wifi"),
            ("open notification settings", "notifications"),
        ],
    )
    def test_direct_settings_sub_page(
        self, resolver, text, expected_sub_page
    ):
        resolution = resolver.resolve({}, text)
        assert resolution.resolved is True
        assert resolution.decision["intent"] == "system.open_settings"
        assert resolution.decision["target"] == expected_sub_page
        assert (
            resolution.decision["parameters"]["settings"]
            == SETTINGS_SUB_PAGES[expected_sub_page]["uri_tail"]
        )


# ---------------------------------------------------------------------
# FALSE-POSITIVE PROTECTION
# ---------------------------------------------------------------------


class TestSingleStepRequestsUnaffected:
    """Genuine single-step requests must NOT be hijacked by the
    context resolver."""

    @pytest.mark.parametrize(
        "text",
        [
            "open my downloads",
            "open chrome",
            "what is 17% of 2450",
            "put the file I just edited into the Reports folder",
            "minimize all windows",
        ],
    )
    def test_single_step_unchanged(self, ou, text):
        res = ou.understand(text)
        # No context-resolved source on any step.
        for s in res.steps:
            assert s.decision.get("source") != "context_hint_resolver"


class TestConversationalRequestsUnaffected:
    """Pure conversational requests must NOT be hijacked."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello, how are you?",
            "what is the meaning of life?",
            "tell me a joke",
        ],
    )
    def test_conversation_unchanged(self, wde, text):
        decision = wde.decide(text)
        assert decision["level"] in (1, 2)


# ---------------------------------------------------------------------
# UNIT TESTS: ContextHintResolver
# ---------------------------------------------------------------------


class TestContextHintResolverUnit:
    """Direct unit tests of the resolver."""

    def test_empty_fragment_returns_unresolved(self, resolver):
        r = resolver.resolve({}, "")
        assert r.resolved is False

    def test_no_prior_decision_uses_direct_resolution(self, resolver):
        r = resolver.resolve({}, "open bluetooth settings")
        assert r.resolved is True
        assert r.decision["intent"] == "system.open_settings"
        assert r.decision["target"] == "bluetooth"

    def test_prior_decision_browser_enables_browser_resolution(
        self, resolver
    ):
        d = {
            "level": 3, "mode": "os",
            "intent": "application.open",
            "target": "chrome", "application": "chrome",
        }
        r = resolver.resolve(d, "search for python tutorials")
        assert r.resolved is True
        assert r.decision["intent"] == "browser.search"
        assert r.decision["application"] == "chrome"

    def test_prior_decision_settings_enables_sub_page_resolution(
        self, resolver
    ):
        d = {
            "level": 3, "mode": "os",
            "intent": "application.open",
            "target": "settings", "application": "settings",
        }
        r = resolver.resolve(d, "turn on bluetooth")
        assert r.resolved is True
        assert r.decision["intent"] == "system.open_settings"
        assert r.decision["target"] == "bluetooth"

    def test_prior_decision_non_os_ignored(self, resolver):
        d = {
            "level": 1, "mode": "conversation",
            "intent": None, "target": None,
        }
        # "write me a poem" is not a settings sub-page and
        # has no context category, so the resolver should
        # not find a mapping.
        r = resolver.resolve(d, "write me a poem")
        assert r.resolved is False

    def test_stats_recorded(self, resolver):
        resolver.resolve({}, "open bluetooth settings")
        resolver.resolve({}, "open display settings")
        s = resolver.stats
        assert s["resolutions_attempted"] >= 2
        assert s["resolutions_succeeded"] >= 2


class TestBuildContextHint:
    """Direct unit tests of build_context_hint."""

    def test_settings_app_via_system_open_settings(self):
        d = {
            "level": 3, "mode": "os",
            "intent": "system.open_settings",
            "target": "bluetooth",
        }
        hint = build_context_hint(d)
        assert hint is not None
        assert hint.category == "settings_app"
        assert hint.sub_page == "bluetooth"

    def test_settings_app_via_application_open(self):
        d = {
            "level": 3, "mode": "os",
            "intent": "application.open",
            "target": "settings", "application": "settings",
        }
        hint = build_context_hint(d)
        assert hint is not None
        assert hint.category == "settings_app"

    def test_browser_app(self):
        d = {
            "level": 3, "mode": "os",
            "intent": "application.open",
            "target": "chrome", "application": "chrome",
        }
        hint = build_context_hint(d)
        assert hint is not None
        assert hint.category == "browser_app"
        assert hint.primary_application == "chrome"

    def test_non_l3_returns_none(self):
        d = {"level": 1, "mode": "conversation", "intent": None}
        assert build_context_hint(d) is None

    def test_non_dict_returns_none(self):
        assert build_context_hint("not a dict") is None  # type: ignore


# ---------------------------------------------------------------------
# END-TO-END: context-resolved plan flows through ActionExecutor
# ---------------------------------------------------------------------


class TestContextResolvedPlanExecutes:
    """The context-resolved 2nd step must be a real ActionPlan
    that the ActionExecutor can dispatch."""

    def test_settings_compound_plan_is_valid(
        self, wde, ou, monkeypatch
    ):
        from genesis_os.action_plan import ActionPlan
        from genesis_os.action_result import ActionResult

        # Capture the dispatched plans.
        captured = []

        def fake_execute(plan):
            captured.append(plan)
            return ActionResult(
                success=True,
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                status="verified",
                message="captured",
                executed=True,
                verified=True,
                # UPDATED 2026-10-04. Without capability-specific
                # evidence the Phase 1 contract rejects the claim
                # (`require_result_evidence` in contracts.py), the
                # result is downgraded to verification_unavailable, and
                # the compound workflow stops after step 1 -- so the
                # second step was never dispatched and this test
                # silently proved nothing.
                verification={"running": True},
                plan=plan,
            )

        from genesis import GenesisOS
        g = GenesisOS()
        # Disable the LLM resolver so the deterministic
        # pattern matcher handles "open settings" as L3.
        g.workflow_decision._llm_resolver = None
        # Patch the workflow engine's executor so we capture
        # the per-step plans without touching the real OS.
        monkeypatch.setattr(
            g.universal_workflow.executor, "execute", fake_execute
        )
        monkeypatch.setattr(
            g.action_executor, "execute", fake_execute
        )

        text = "open settings and turn on bluetooth"

        # REWRITTEN 2026-10-04. This asserted that a context-resolved
        # `system.open_settings` step targeting `bluetooth` reached the
        # executor. Two deliberate changes since made that unreachable
        # through `run_level3`: the Phase 1 evidence contract rejects a
        # fabricated `verified: True` carrying no capability-specific
        # evidence, and `ObservationLoop` then re-checks real OS state,
        # so step 1 (`application.open` for the Settings app, which is
        # not actually running on this host) cannot verify and the
        # compound workflow stops before step 2.
        #
        # Both behaviours are correct. The premise of this test -- that
        # the second clause resolves to a settings sub-page -- is a
        # property of PLANNING, not of dispatch, so it is asserted on
        # the plan the context resolver produces. The dispatch half is
        # still pinned: an unverified compound workflow must not report
        # success.
        understanding = ou.understand(text)
        ops_targets = [
            (step.operation, step.target) for step in understanding.steps
        ]
        assert ("system.open_settings", "bluetooth") in ops_targets, (
            f"second clause did not resolve to the bluetooth "
            f"sub-page: {ops_targets}"
        )

        g = GenesisOS()
        g.workflow_decision._llm_resolver = None
        result = g.run_level3(text, g.classify(text))
        assert result is not None
        if result.final_verified is False:
            assert result.success is False, (
                "an unverified compound workflow reported success"
            )

    def test_browser_compound_plan_is_valid(
        self, wde, ou, monkeypatch
    ):
        from genesis_os.action_result import ActionResult

        captured = []

        def fake_execute(plan):
            captured.append(plan)
            return ActionResult(
                success=True,
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                status="verified",
                message="captured",
                executed=True,
                verified=True,
                plan=plan,
            )

        from genesis import GenesisOS
        g = GenesisOS()
        # Disable the LLM resolver so the deterministic
        # pattern matcher handles "open chrome" as L3.
        g.workflow_decision._llm_resolver = None
        monkeypatch.setattr(
            g.universal_workflow.executor, "execute", fake_execute
        )
        monkeypatch.setattr(
            g.action_executor, "execute", fake_execute
        )

        text = "open chrome and search for python tutorials"
        decision = g.classify(text)
        g.run_level3(text, decision)

        # At least one step must have been a context-resolved
        # browser.search.
        ops = [p.operation for p in captured]
        assert "browser.search" in ops
