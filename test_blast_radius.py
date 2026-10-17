"""Genesis OS — dynamic blast-radius evaluation.

Tests the decision mechanism in isolation: no enforcement anywhere in
this file. What is pinned here is

  1. a capability with NO evaluator resolves to its static default
     exactly — adding the mechanism must not perturb anything that did
     not opt into it;
  2. a registered evaluator escalates when it fires and falls back to
     the static default when it declines;
  3. THE NO-DOWNGRADE INVARIANT — an evaluator can only ever make a
     capability MORE restricted. A less-restrictive verdict is
     discarded in favour of the declared floor;
  4. a broken evaluator fails safe (floor kept), never open.

The enforcement wiring that will consume these tiers is explicitly out
of scope for this file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.blast_radius import (
    HIGH_RISK_CLICK_SIGNALS,
    browser_click_escalation,
    click_risk_signal,
    dynamic_evaluator_for,
    has_dynamic_evaluator,
    more_restrictive,
    overwrite_destination_escalation,
    register_dynamic_evaluator,
    resolve_blast_radius,
)
from genesis_os.capabilities import BlastRadius

IRREVERSIBLE = BlastRadius.IRREVERSIBLE_OR_OUTWARD
REVERSIBLE = BlastRadius.REVERSIBLE_LOCAL


@pytest.fixture(autouse=True)
def _clean_registry():
    """Evaluator registration is module-global; isolate each test."""
    from genesis_os import blast_radius as BR

    saved = dict(BR._evaluators)
    BR._evaluators.clear()
    BR._register_builtin_evaluators()
    try:
        yield
    finally:
        BR._evaluators.clear()
        BR._evaluators.update(saved)


# =========================================================
# 1. NO EVALUATOR = NO NEW BEHAVIOUR
# =========================================================


class TestNoEvaluatorMeansNoChange:
    def test_capability_without_evaluator_returns_static_default(self):
        for default in (REVERSIBLE, IRREVERSIBLE):
            resolved = resolve_blast_radius(
                "application.open",
                {"application": "notepad"},
                static_default=default,
            )
            assert resolved is default

    def test_unknown_capability_with_no_declared_default_is_denied(self):
        """Fail closed: an id nothing declares is treated as Tier 1."""
        assert resolve_blast_radius(
            "totally.unknown.capability", {}, static_default=None
        ) is IRREVERSIBLE

    def test_arguments_are_irrelevant_without_an_evaluator(self, workspace_root):
        """Bucket (a): premise false by design, rewritten not deleted.

        "No evaluator means arguments are irrelevant" was true only
        while the workspace boundary was inactive. Under activation a
        capability with no evaluator still keeps its static tier for
        in-workspace arguments, but an argument that leaves the root
        escalates. The new truth is asserted below.
        """
        inside_a = resolve_blast_radius(
            "x.y", {"path": str(workspace_root / "a")}, static_default=REVERSIBLE
        )
        inside_b = resolve_blast_radius(
            "x.y", {"path": str(workspace_root / "b")}, static_default=REVERSIBLE
        )
        # Which in-workspace file is named does not change the tier.
        assert inside_a is inside_b is REVERSIBLE
        # Leaving the root does, even with no evaluator registered.
        assert resolve_blast_radius(
            "x.y",
            {"path": str(workspace_root.parent / "elsewhere")},
            static_default=REVERSIBLE,
        ) is IRREVERSIBLE


# =========================================================
# 2. THE NO-DOWNGRADE INVARIANT
# =========================================================


class TestNoDowngradeInvariant:
    def test_evaluator_cannot_loosen_a_restrictive_static_default(self):
        register_dynamic_evaluator(
            "locked.cap", lambda args, ctx: REVERSIBLE
        )
        resolved = resolve_blast_radius(
            "locked.cap", {}, static_default=IRREVERSIBLE
        )
        assert resolved is IRREVERSIBLE, (
            "an evaluator returned the laxer tier; the declared floor "
            "must win"
        )

    def test_evaluator_may_tighten_a_permissive_static_default(self):
        register_dynamic_evaluator(
            "escalating.cap", lambda args, ctx: IRREVERSIBLE
        )
        resolved = resolve_blast_radius(
            "escalating.cap", {}, static_default=REVERSIBLE
        )
        assert resolved is IRREVERSIBLE

    def test_more_restrictive_helper_never_returns_the_laxer_tier(self):
        assert more_restrictive(IRREVERSIBLE, REVERSIBLE) is IRREVERSIBLE
        assert more_restrictive(REVERSIBLE, IRREVERSIBLE) is IRREVERSIBLE
        assert more_restrictive(REVERSIBLE, REVERSIBLE) is REVERSIBLE
        assert more_restrictive(IRREVERSIBLE, IRREVERSIBLE) is IRREVERSIBLE

    def test_evaluator_returning_none_keeps_static_default(self):
        register_dynamic_evaluator("declines.cap", lambda args, ctx: None)
        assert resolve_blast_radius(
            "declines.cap", {}, static_default=REVERSIBLE
        ) is REVERSIBLE
        assert resolve_blast_radius(
            "declines.cap", {}, static_default=IRREVERSIBLE
        ) is IRREVERSIBLE

    def test_evaluator_returning_garbage_keeps_static_default(self):
        register_dynamic_evaluator("junk.cap", lambda args, ctx: "nope")
        assert resolve_blast_radius(
            "junk.cap", {}, static_default=REVERSIBLE
        ) is REVERSIBLE

    def test_evaluator_that_raises_fails_closed_to_the_floor(self):
        def explode(args, ctx):
            raise RuntimeError("provider blew up")

        register_dynamic_evaluator("boom.cap", explode)
        assert resolve_blast_radius(
            "boom.cap", {}, static_default=REVERSIBLE
        ) is REVERSIBLE
        assert resolve_blast_radius(
            "boom.cap", {}, static_default=IRREVERSIBLE
        ) is IRREVERSIBLE


# =========================================================
# 3. REGISTRATION VALIDATION
# =========================================================


class TestRegistration:
    def test_non_callable_rejected(self):
        with pytest.raises(TypeError):
            register_dynamic_evaluator("some.cap", "not a function")

    def test_blank_capability_id_rejected(self):
        with pytest.raises(ValueError):
            register_dynamic_evaluator("   ", lambda a, c: None)

    def test_duplicate_registration_requires_explicit_replace(self):
        register_dynamic_evaluator("dup.cap", lambda a, c: None)
        with pytest.raises(ValueError):
            register_dynamic_evaluator("dup.cap", lambda a, c: IRREVERSIBLE)
        register_dynamic_evaluator(
            "dup.cap", lambda a, c: IRREVERSIBLE, replace=True
        )
        assert resolve_blast_radius(
            "dup.cap", {}, static_default=REVERSIBLE
        ) is IRREVERSIBLE


# =========================================================
# 4. EVALUATOR 1 — browser.click
# =========================================================


class TestBrowserClickEvaluator:
    def test_registered_by_default(self):
        assert has_dynamic_evaluator("browser.click") is True
        assert dynamic_evaluator_for("browser.click") is not None

    @pytest.mark.parametrize(
        "text",
        [
            "Delete account",
            "BUY NOW",
            "unsubscribe",
            "Wire transfer",
            "checkout",
        ],
    )
    def test_high_risk_signal_escalates(self, text):
        assert resolve_blast_radius(
            "browser.click",
            {},
            static_default=REVERSIBLE,
            context={"element_text": text},
        ) is IRREVERSIBLE

    @pytest.mark.parametrize(
        "text",
        ["Read more", "Next page", "Documentation", "Pricing"],
    )
    def test_ordinary_link_stays_reversible(self, text):
        assert resolve_blast_radius(
            "browser.click",
            {},
            static_default=REVERSIBLE,
            context={"element_text": text},
        ) is REVERSIBLE

    def test_unassessable_element_escalates(self):
        """No readable text at all -> unknown risk, not assumed safe."""
        assert resolve_blast_radius(
            "browser.click",
            {},
            static_default=REVERSIBLE,
            context={"_no_element_text": True},
        ) is IRREVERSIBLE

    def test_alt_text_and_aria_label_are_also_inspected(self):
        for key in ("alt_text", "aria_label"):
            assert resolve_blast_radius(
                "browser.click",
                {},
                static_default=REVERSIBLE,
                context={key: "Delete"},
            ) is IRREVERSIBLE

    def test_signal_detection_helper_is_case_insensitive(self):
        assert click_risk_signal("please DELETE this") == "delete"
        assert click_risk_signal("nothing risky here") is None
        assert click_risk_signal(None) is None

    def test_signal_list_is_shared_with_security_model(self):
        """The heuristic has exactly one definition, not two.

        Checked via the AST rather than a substring match, because
        security_model's docstring legitimately *names* the signals in
        prose ("buy", "purchase", ...) while describing the behaviour.
        What must not exist is a second collection literal in code.
        """
        import ast
        import inspect

        from genesis_os import security_model

        tree = ast.parse(inspect.getsource(security_model))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                value = node.value
                is_collection = isinstance(
                    value, (ast.Set, ast.List, ast.Tuple, ast.Dict)
                ) or (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "frozenset"
                )
                if not is_collection:
                    # A scalar holding the shared detector's *result*
                    # is the desired shape, not a second definition.
                    continue
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and "SIGNAL" in target.id.upper()
                    ):
                        offenders.append(target.id)
        assert not offenders, (
            f"security_model still declares its own signal collection: "
            f"{offenders}"
        )
        assert "delete" in HIGH_RISK_CLICK_SIGNALS

    def test_security_model_delegates_to_the_shared_detector(self):
        import inspect

        from genesis_os import security_model

        assert "click_risk_signal" in inspect.getsource(
            security_model.assess_operation_risk
        )

    def test_evaluator_is_pure(self):
        first = browser_click_escalation({}, {"element_text": "Delete"})
        second = browser_click_escalation({}, {"element_text": "Delete"})
        assert first is second is IRREVERSIBLE


# =========================================================
# 6. EVALUATOR 3 — application.close (unsaved work)
# =========================================================


class TestApplicationCloseEvaluator:
    def test_registered_by_default(self):
        assert has_dynamic_evaluator("application.close") is True

    def test_unsaved_work_escalates_to_tier_1(self):
        from genesis_os import blast_radius as BR

        BR.register_unsaved_changes_detector(
            "application.close", lambda args: (True, "unsaved work detected")
        )
        assert resolve_blast_radius(
            "application.close",
            {"application": "notepad"},
            static_default=REVERSIBLE,
        ) is IRREVERSIBLE

    def test_no_unsaved_work_stays_tier_2(self):
        from genesis_os import blast_radius as BR

        BR.register_unsaved_changes_detector(
            "application.close", lambda args: (False, "no unsaved state")
        )
        assert resolve_blast_radius(
            "application.close",
            {"application": "calculator"},
            static_default=REVERSIBLE,
        ) is REVERSIBLE

    def test_missing_detector_does_not_escalate_blindly(self):
        """A MISSING platform detector must not prompt on every routine
        close.

        Item 10B (S11): this docstring used to justify that by
        pointing at a downstream execution-safety backstop for false
        negatives. That was FALSE -- ExecutionSafety.check() is a
        deny-list plus a capability lookup and never inspects unsaved
        state. The behaviour below is still correct, but it rests on a
        product trade-off (do not prompt on an unsupported platform), not
        on a backstop that does not exist.

        Note this covers the MISSING-detector case only. A REGISTERED
        detector that raises escalates, by
        test_throwing_detector_escalates_fail_closed.
        """
        from genesis_os import blast_radius as BR

        saved = BR._unsaved_changes_detectors.pop("application.close", None)
        try:
            assert resolve_blast_radius(
                "application.close", {}, static_default=REVERSIBLE
            ) is REVERSIBLE
        finally:
            if saved is not None:
                BR._unsaved_changes_detectors["application.close"] = saved

    def test_throwing_detector_escalates_fail_closed(self):
        """A REGISTERED detector that raises is an error, not a verdict.

        Directive 7B. This previously asserted the opposite
        (`test_throwing_detector_does_not_escalate_blindly`): the
        handler returned None, which the caller cannot distinguish from
        "checked, found nothing", so a crashed detector silently
        downgraded application.close to its static tier and allowed a
        close with possible unsaved work through ungated.
        """
        from genesis_os import blast_radius as BR

        def boom(args):
            raise RuntimeError("user32 unavailable")

        BR.register_unsaved_changes_detector("application.close", boom)
        assert resolve_blast_radius(
            "application.close", {}, static_default=REVERSIBLE
        ) is IRREVERSIBLE

    def test_unsupported_platform_verdict_does_not_escalate(self):
        """No regression on the prompt-on-every-close path.

        The fail-closed fix above must NOT fire when the platform is
        simply unsupported, because both such paths RETURN a verdict
        rather than raising: the ctypes import failure yields
        (False, "user32 unavailable on this platform"). Those must keep
        the unelevated tier, or every routine close would prompt.
        """
        from genesis_os import blast_radius as BR

        saved = BR._unsaved_changes_detectors.get("application.close")
        try:
            BR.register_unsaved_changes_detector(
                "application.close",
                lambda args: (False, "user32 unavailable on this platform"),
            )
            assert resolve_blast_radius(
                "application.close", {}, static_default=REVERSIBLE
            ) is REVERSIBLE
        finally:
            if saved is not None:
                BR._unsaved_changes_detectors["application.close"] = saved

    def test_adapter_precondition_defers_to_the_evaluator(self):
        """One authority: the adapter's precondition gate must not
        decide independently of the tier."""
        from genesis_os.agent_framework_adapter import (
            AgentFrameworkAdapter,
        )

        adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)
        adapter._has_unsaved_windows_for_application_close = (
            lambda arguments: (True, "unsaved state visible")
        )
        active, reason = adapter._check_unsaved_changes_precondition(
            capability_id="application.close",
            arguments={"application": "notepad"},
        )
        assert active is True
        assert "unsaved" in reason.lower()

        adapter._has_unsaved_windows_for_application_close = (
            lambda arguments: (False, "clean")
        )
        active, _ = adapter._check_unsaved_changes_precondition(
            capability_id="application.close",
            arguments={"application": "calculator"},
        )
        assert active is False


# =========================================================
# 8. STEP 0 — coverage gap closure + general fallback
# =========================================================


class TestShutdownRestartClassified:
    @pytest.mark.parametrize(
        "capability_id", ["system.shutdown", "system.restart"]
    )
    def test_registered_and_tier_1(self, capability_id):
        from genesis_os.capability_registry import CapabilityRegistry

        descriptor = CapabilityRegistry.get(capability_id)
        assert descriptor.blast_radius is IRREVERSIBLE

    @pytest.mark.parametrize(
        "capability_id", ["system.shutdown", "system.restart"]
    )
    def test_registered_unavailable_not_as_a_phantom(self, capability_id):
        """Neither OSManager nor ActionExecutor implements these. They
        must be classified AND marked unavailable, so the registry does
        not advertise a capability that cannot run."""
        from genesis_os.capabilities import CapabilityAvailability
        from genesis_os.capability_registry import CapabilityRegistry

        descriptor = CapabilityRegistry.get(capability_id)
        assert descriptor.availability is CapabilityAvailability.UNAVAILABLE

    def test_reason_records_the_coverage_gap_it_closed(self):
        from genesis_os.capability_registry import CapabilityRegistry

        reason = CapabilityRegistry.get("system.shutdown").blast_radius_reason
        assert "dangerous_operations" in reason
        assert "invisible" in reason


class TestUnregisteredOperationFallback:
    def test_dangerous_but_unregistered_resolves_tier_1_and_is_logged(self):
        """filesystem.delete is in _dangerous_operations but has no
        descriptor. It must not fall through ungated."""
        from genesis_os import blast_radius as BR
        from genesis_os.capability_registry import CapabilityRegistry

        assert "filesystem.delete" in CapabilityRegistry._dangerous_operations
        assert (
            BR.resolve_operation_blast_radius("filesystem.delete")
            is IRREVERSIBLE
        )
        gaps = [
            g for g in BR.coverage_gaps()
            if g["operation"] == "filesystem.delete"
        ]
        assert gaps, "the coverage gap was not recorded"
        assert gaps[0]["declared_dangerous"] is True

    def test_entirely_unknown_operation_is_tier_1_and_logged(self):
        from genesis_os import blast_radius as BR

        assert (
            BR.resolve_operation_blast_radius("totally.unknown.op")
            is IRREVERSIBLE
        )
        gaps = [
            g for g in BR.coverage_gaps()
            if g["operation"] == "totally.unknown.op"
        ]
        assert gaps and gaps[0]["declared_dangerous"] is False

    def test_registered_capability_resolves_through_its_own_tier(self):
        """The fallback must not flatten genuine Tier 2 capabilities."""
        from genesis_os import blast_radius as BR

        assert (
            BR.resolve_operation_blast_radius("file.create") is REVERSIBLE
        )

    def test_gap_log_deduplicates(self):
        from genesis_os import blast_radius as BR

        before = len(BR.coverage_gaps())
        for _ in range(3):
            BR.resolve_operation_blast_radius("dedup.probe.op")
        after = [
            g for g in BR.coverage_gaps()
            if g["operation"] == "dedup.probe.op"
        ]
        assert len(after) == 1, f"gap logged {len(after)} times"
        assert len(BR.coverage_gaps()) >= before


# =========================================================
# 7. EVALUATOR 2 — move / rename destination exists
# =========================================================


class TestOverwriteDestinationEvaluator:
    @pytest.mark.parametrize(
        "capability_id",
        ["file.move", "file.rename", "folder.move", "folder.rename"],
    )
    def test_registered_for_all_move_and_rename_capabilities(
        self, capability_id
    ):
        assert has_dynamic_evaluator(capability_id) is True

    def test_free_destination_stays_reversible(self, workspace_root):
        target = workspace_root / "new.txt"
        assert resolve_blast_radius(
            "file.move",
            {"source": str(workspace_root / "a.txt"), "destination": str(target)},
            static_default=REVERSIBLE,
        ) is REVERSIBLE

    def test_destination_outside_workspace_escalates(self, tmp_path, workspace_root):
        """Counterpart for the free-destination test (bucket b).

        Same operation, same free destination, but outside the root:
        the boundary must escalate it. Without this pair the retargeted
        test would pass vacuously -- a free destination inside the
        workspace stays reversible whether or not the boundary works.
        """
        outside = tmp_path / "outside.txt"
        assert resolve_blast_radius(
            "file.move",
            {"source": str(workspace_root / "a.txt"), "destination": str(outside)},
            static_default=REVERSIBLE,
        ) is IRREVERSIBLE

    def test_existing_destination_escalates(self, tmp_path):
        existing = tmp_path / "already-there.txt"
        existing.write_text("precious")
        assert resolve_blast_radius(
            "file.move",
            {"source": str(tmp_path / "a.txt"), "destination": str(existing)},
            static_default=REVERSIBLE,
        ) is IRREVERSIBLE

    def test_no_destination_declined(self):
        assert overwrite_destination_escalation({"source": "/tmp/a"}, None) is None

    def test_non_mapping_arguments_declined(self):
        assert overwrite_destination_escalation(None, None) is None

    def test_directory_destination_counts_as_existing(self, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        assert resolve_blast_radius(
            "file.rename",
            {"source": str(tmp_path / "a.txt"), "destination": str(d)},
            static_default=REVERSIBLE,
        ) is IRREVERSIBLE

    def test_alternate_destination_argument_names_are_honoured(self, tmp_path):
        occupied = tmp_path / "taken.txt"
        occupied.write_text("x")
        for key in ("destination", "output", "output_path", "save_path"):
            assert resolve_blast_radius(
                "file.move",
                {"source": str(tmp_path / "a.txt"), key: str(occupied)},
                static_default=REVERSIBLE,
            ) is IRREVERSIBLE, f"key {key} was not inspected"
