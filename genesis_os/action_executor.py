"""
Genesis OS â€” Action Executor

LEVEL 3.6
---------

Central execution gateway.

Responsibilities:

    - validate ActionPlan structure
    - distinguish missing/invalid targets
    - evaluate ExecutionSafety before execution
    - block denied/unknown operations
    - enforce confidence
    - dispatch only approved operations
    - preserve execution evidence
    - preserve verification evidence
    - derive deterministic status
    - establish trustworthy success
    - preserve safety decisions
    - never allow blocked operations to reach OSManager

Pipeline:

    ActionPlan
        â†“
    Structural Validation
        â†“
    Target Validation
        â†“
    ExecutionSafety
        â†“
    ActionPlan Capability Validation
        â†“
    Dispatch
        â†“
    Result Normalization
        â†“
    ActionResult
"""

from __future__ import annotations

import logging
import concurrent.futures


def _resolved_capability(
    operation: str, capability_id: Optional[str] = None
) -> Optional[str]:
    """The registered capability for these identifiers, or None."""
    try:
        from .blast_radius import identify_capability

        return identify_capability(operation, capability_id)
    except Exception:
        return None


def _operation_requires_authorization(
    operation: str,
    capability_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Does this require a human-approval grant?

    THE single source of truth for "is this Tier 1", shared by the
    adapter gate and the executor gate. Reads ``blast_radius`` only.

    ``risk_level`` / ``security_model.requires_confirmation`` is
    deliberately NOT consulted: those answer "how scary", not "can it
    be taken back", and they disagree on 57 capabilities by design.

    WHY BOTH IDENTIFIERS
    ---------------------
    ``operation`` alone is insufficient: browser capabilities register
    with the bare verb ("click"), which matches no capability's
    operation field, and deny-by-default then gated 31 legitimate Tier
    2 browser capabilities. ``capability_id`` alone is insufficient
    because direct executor callers (tests, the L2/L3 pipeline) never
    set it.

    So BOTH are consulted and the MORE RESTRICTIVE answer wins. That is
    fail-safe by construction: a missing or wrong ``capability_id`` can
    only make a plan more gated, never less.

    Deny-by-default: an operation that cannot be classified at all is
    Tier 1.
    """
    try:
        from .blast_radius import (
            BlastRadius,
            resolve_blast_radius,
            resolve_operation_blast_radius,
        )

        # arguments MUST be passed: the dynamic evaluators (move/rename
        # overwrite, browser.click signal words, application.close
        # unsaved work) decide the tier from the specific call. Calling
        # this without them silently disabled every evaluator at the
        # executor layer.
        #
        # context MUST be passed for the same reason. `browser.click`
        # escalation reads the target element's accessible text, and only
        # the executor can obtain that (it may have to ask the live
        # browser). Omitting it made that evaluator unreachable at the
        # gate: the escalation was computed and then discarded.
        tier = resolve_operation_blast_radius(
            operation,
            dict(arguments or {}),
            capability_id=capability_id,
            context=dict(context) if context else None,
        )

        if capability_id:
            try:
                by_capability = resolve_blast_radius(
                    capability_id, {}, static_default=tier
                )
            except Exception:
                by_capability = BlastRadius.IRREVERSIBLE_OR_OUTWARD
            # Most restrictive of the two wins.
            if by_capability is BlastRadius.IRREVERSIBLE_OR_OUTWARD:
                tier = by_capability
    except Exception:
        return True
    return tier is BlastRadius.IRREVERSIBLE_OR_OUTWARD


def _values_match(left: Any, right: Any) -> bool:
    """Whether two argument values are the same dispatched value.

    Item 20A: used to reconcile the approved arguments with the ones
    ``_dispatch`` reads. Direct equality first; a str/other mix (a Path
    against its string form) falls back to string comparison so a
    legitimate plan is not refused for a type difference alone. The
    comparison is still fail-closed: anything not matching here denies.
    """
    if left == right:
        return True
    if left is None or right is None:
        return False
    if isinstance(left, str) or isinstance(right, str):
        return str(left) == str(right)
    return False


from typing import Any, Dict

from genesis_os.action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)

from genesis_os.action_result import (
    ActionResult,
)
from genesis_os.contracts import (
    ContractViolationError,
    Evidence as EvidenceContract,
    Execution as ExecutionContract,
    Task as TaskContract,
    require_result_evidence,
)

from genesis_os.execution_safety import (
    ExecutionSafety,
    SafetyDecision,
)
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.capability_catalog import CAPABILITIES
from genesis_os.error_handler import ErrorHandler, explain_error
from genesis_os.runtime_focus_resolver import (
    RuntimeFocusResolver,
    RuntimeFocusResolution,
)
from genesis_os.security_model import SecurityManager, requires_confirmation

logger = logging.getLogger("genesis_os.action_executor")


class ActionExecutor:
    """
    Central Level 3 execution gateway.

    No operation reaches OSManager unless:

        1. the ActionPlan is structurally valid
        2. the target is valid
        3. ExecutionSafety allows the operation
        4. capability validation succeeds
    """

    VERSION = "3.6.0"

    EXECUTION_CONTRACT = "3.6"

    SUPPORTED_OPERATIONS = frozenset({
        "application.open", "application.close", "application.inspect", "application.list",
        "application.focus", "application.window_list",
        "file.inspect", "file.read", "file.search", "file.hash", "file.open",
        "file.create", "file.copy", "file.move", "file.rename", "file.delete",
        "folder.inspect", "folder.create", "folder.open", "folder.organize", "folder.rename", "folder.move", "folder.delete",
        "process.list", "process.inspect",
        "browser.open_url", "browser.search",
        "system.status", "system.open_settings",
        "network.list_wifi", "network.connect_wifi",
        "spreadsheet.sort", "document.create_docx",
        # Level 3.10 — universal desktop control
        "media.play_pause", "media.next", "media.previous", "media.stop",
        "volume.up", "volume.down", "volume.mute_toggle", "volume.set", "volume.get",
        "display.brightness_set", "display.brightness_get",
        "hardware.battery", "hardware.stats",
        "clipboard.copy", "clipboard.paste",
        "screen.capture",
        "workstation.lock",
        "web.research",
        # Level 3.12 — windows, daily intelligence, notes,
        # packages, cleanup
        "window.minimize_all", "window.restore", "window.show_desktop",
        "web.weather", "time.world_clock", "math.evaluate", "hardware.storage",
        "notes.create", "notes.list",
        "package.search", "package.install", "package.uninstall",
        "cleanup.recycle_bin_query", "cleanup.empty_recycle_bin",
        # Level 3.13 — advanced browser intelligence
        "browser.click", "browser.type", "browser.scroll", "browser.find",
        "browser.extract", "browser.get_title", "browser.get_url",
        "browser.switch_tab", "browser.open_tab", "browser.close_tab",
        "browser.get_tabs", "browser.wait", "browser.screenshot",
        "browser.verify", "browser.capabilities",
        "browser.select", "browser.download", "browser.upload",
        # Level 3.14 — GUI interaction (core)
        "gui.focus_window", "gui.inspect_window", "gui.click", "gui.double_click",
        "gui.type_text", "gui.paste_text", "gui.read_visible_text",
        "gui.select", "gui.scroll", "gui.keyboard_action",
        # Phase 6 — GUI interaction (extended)
        "gui.hotkey", "gui.drag", "gui.wait", "gui.wait_for_window",
        "gui.inspect_ui_tree",
        # Level 3.14 — Document intelligence (multi-format)
        "document.inspect", "document.read", "document.search",
        "document.search_intel",
        "document.create_txt", "document.create_docx", "document.create_csv",
        "document.create_json", "document.create_markdown", "document.create_pdf",
        "document.compare", "document.summarize",
        "document.edit", "document.transform", "document.verify",
        # Level 3.14 — Spreadsheet intelligence (multi-operation)
        "spreadsheet.inspect", "spreadsheet.read", "spreadsheet.sort",
        "spreadsheet.filter", "spreadsheet.calculate", "spreadsheet.rank",
        "spreadsheet.group_by", "spreadsheet.aggregate", "spreadsheet.compare",
        "spreadsheet.add_column", "spreadsheet.update_cell", "spreadsheet.create_from_dicts",
        "application.inspect_window_content", "browser.get_page_state",
        "file.watch", "filesystem.open", "filesystem.search",
        "document.create", "gui.wait_for_state", "weather.current",
    })

    SUPPORTED_OPERATIONS = CAPABILITIES

    MINIMUM_CONFIDENCE = 0.90

    def __init__(
        self,
        os_manager,
    ):
        if os_manager is None:
            raise ValueError(
                "ActionExecutor requires an OSManager."
            )

        self.os_manager = os_manager

    # =========================================================
    # AUTHORIZATION GATE (Item 20A / S14)
    # =========================================================

    def _authorization_gate(
        self,
        plan: ActionPlan,
        security_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ActionResult]:
        """Refuse a Tier 1 plan whose dispatch is not what was approved.

        Returns the refusal ``ActionResult``, or ``None`` when the plan
        may proceed (Tier 2, or a grant that covers this exact dispatch).

        WHY THIS EXISTS AS ONE METHOD (Item 20A, S14):

        The gate used to be inline at the bottom of ``execute`` only,
        with two consequences:

          * every ``plan.target is None`` path returned BEFORE reaching
            it, so a Tier 1 targetless operation (``file.search``
            against an outside path) dispatched with no grant at all;
          * it validated ``plan.authorization_arguments`` -- the dict
            the human approved -- while ``_dispatch`` reads
            ``plan.parameters``. A grant for {source: A, destination: B}
            executed a plan whose parameters said destination: C.

        The check and the dispatch must be about the SAME arguments, so
        after the grant's own hash validation the approved set is
        reconciled against what will actually run
        (``plan.parameters`` + ``plan.target`` + ``plan.application``):

          1. every approved value must be the value dispatched -- a key
             present in both must be equal; an approved target-bearing
             key absent from parameters must be the plan's own
             target/application (the adapter legitimately carries the
             primary identifier as ``target`` rather than a parameter),
             and any other target-bearing absence refuses; a dropped
             non-target-bearing key cannot redirect dispatch and passes;
          2. every target-bearing argument the plan carries must have
             been approved -- the human never saw an injected one;
          3. the plan's target must be among the approved target-bearing
             values whenever the grant approved substantive arguments
             (substance measured by the canonical approval hash).

        Any mismatch refuses. There is no path through this method that
        turns an inconsistency into a pass.
        """
        if not _operation_requires_authorization(
            plan.operation,
            getattr(plan, "capability_id", None),
            plan.parameters,
            context=security_context if security_context else None,
        ):
            return None

        from .authorization_grant import (
            grant_is_valid_for,
            TARGET_BEARING_ARGUMENT_KEYS,
        )
        from .approval_store import _approval_arguments_hash

        grant = getattr(plan, "authorization", None)
        approved_arguments = getattr(
            plan, "authorization_arguments", None
        )
        try:
            authorized = grant_is_valid_for(
                grant,
                operation=plan.operation,
                arguments=approved_arguments,
            )
        except Exception:
            authorized = False

        # A grant proves the CALLER's arguments were approved; it
        # does not prove this plan is built from them. Without the
        # reconciliation below, a grant for path A could be attached
        # to a plan dispatching path B -- or to a plan carrying an
        # argument no human ever saw.
        denial_reason = "no valid grant"
        channel_keys = {"approval_token", "_authorization_grant"}

        if authorized and approved_arguments is not None:
            approved = dict(approved_arguments)
            dispatched = dict(plan.parameters or {})

            # (1) The approved set and the dispatched set must agree.
            for key, value in approved.items():
                if key in dispatched:
                    if not _values_match(dispatched[key], value):
                        authorized = False
                        denial_reason = (
                            f"approved argument {key!r} differs from the "
                            "value the plan would dispatch"
                        )
                        break
                elif value not in (None, ""):
                    if (
                        _values_match(value, plan.target)
                        or _values_match(value, plan.application)
                    ):
                        continue
                    if key in TARGET_BEARING_ARGUMENT_KEYS:
                        authorized = False
                        denial_reason = (
                            f"approved argument {key!r} is absent from the "
                            "plan that would be dispatched"
                        )
                        break
                    # A non-target-bearing approved key the plan dropped
                    # (``confirmed``, bookkeeping) cannot redirect dispatch:
                    # its absence only ever under-executes, and the
                    # canonical approval hash does not count it either.

            # (2) A target-bearing argument the plan carries must be in
            # the approved set: dispatching a path the approval never
            # named is the S14 hole in its clearest form.
            if authorized:
                approved_keys = set(approved)
                for key, value in dispatched.items():
                    if key in approved_keys or key in channel_keys:
                        continue
                    if (
                        key in TARGET_BEARING_ARGUMENT_KEYS
                        and value not in (None, "")
                    ):
                        authorized = False
                        denial_reason = (
                            f"dispatched target-bearing argument {key!r} "
                            "was never approved"
                        )
                        break

            # (3) Target correspondence, fail closed: the plan's target
            # must be among the approved target-bearing values. When the
            # grant approved arguments but NONE of them can name a
            # target, a targeted plan is refused too. "Approved
            # arguments" is measured the way the canonical approval
            # hash measures it: a set whose hash equals the hash of an
            # empty set approved nothing substantive (only control keys
            # such as ``confirmed``, which the canonicalizer strips),
            # and it passes without target coverage the way a
            # no-argument grant does -- there is no second target for
            # such a grant to be re-pointed at.
            if authorized and plan.target is not None:
                approved_targets = {
                    str(value)
                    for key, value in approved.items()
                    if key in TARGET_BEARING_ARGUMENT_KEYS
                    and value not in (None, "")
                }
                if approved_targets:
                    if str(plan.target) not in approved_targets:
                        authorized = False
                        denial_reason = (
                            "the plan's target is not among the approved "
                            "arguments"
                        )
                elif approved and _approval_arguments_hash(
                    plan.operation, approved
                ) != _approval_arguments_hash(plan.operation, {}):
                    authorized = False
                    denial_reason = (
                        "the grant covers no target-bearing argument, so it "
                        "cannot authorize a targeted plan"
                    )

        if authorized:
            return None

        return ActionResult.failure_result(
            operation=plan.operation,
            target=plan.target,
            application=plan.application,
            message=(
                "This operation is irreversible or outward-facing "
                "and requires a human-approval grant."
            ),
            status="confirmation_required",
            error=(
                f"Authorization required for {plan.operation}: no "
                f"valid grant. Grants travel on the trusted adapter "
                f"channel and cannot be supplied through plan "
                f"parameters."
                + (
                    f" ({denial_reason})"
                    if denial_reason != "no valid grant"
                    else ""
                )
            ),
            executed=False,
            verified=False,
            plan=plan.to_dict(),
            metadata={
                "executor_version": self.VERSION,
                "gate": "blast_radius",
                "blast_radius": "irreversible_or_outward",
                "denial_reason": denial_reason,
            },
        )

    # =========================================================
    # PUBLIC API
    # =========================================================

    def execute(
        self,
        plan: ActionPlan,
        timeout: float = 300.0,
    ) -> ActionResult:
        """
        Safely execute an ActionPlan.

        Args:
            plan: The ActionPlan to execute.
            timeout: Maximum seconds for the execution.
                A hung subprocess will be interrupted.

        On timeout the dispatch worker thread is ABANDONED, not
        killed: a thread cannot be interrupted, so it keeps running
        until the action finishes on its own. What this method
        guarantees is only that the CALL returns at the timeout --
        never that the action was stopped.
        """

        # =====================================================
        # 1. TYPE VALIDATION
        # =====================================================

        if not isinstance(
            plan,
            ActionPlan,
        ):
            return ActionResult.failure_result(
                operation="unknown",
                target=None,
                application=None,
                message=(
                    "Genesis received an invalid "
                    "action plan."
                ),
                status="invalid_plan",
                error=(
                    "ActionExecutor requires an ActionPlan."
                ),
                executed=False,
                verified=False,
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": (
                        self.EXECUTION_CONTRACT
                    ),
                    "validation_stage": "type",
                },
            )

        # =====================================================
        # 2. STRUCTURAL VALIDATION
        #
        # Do NOT reject unsupported capabilities here.
        #
        # ExecutionSafety must be allowed to distinguish:
        #
        #     denied
        #     unknown
        #
        # from malformed operations.
        # =====================================================

        structural_error = (
            self._validate_structure(plan)
        )

        if structural_error is not None:
            return self._invalid_plan_result(
                plan,
                structural_error,
                stage="structure",
            )

        early_safety_decision = ExecutionSafety.check(plan.operation)
        if early_safety_decision.status == "invalid":
            return self._invalid_plan_result(
                plan,
                early_safety_decision.reason,
                stage="safety",
                safety_decision=early_safety_decision,
            )
        if not early_safety_decision.allowed:
            return self._safety_blocked_result(
                plan,
                early_safety_decision,
            )

        # =====================================================
        # 3. TARGET VALIDATION
        # =====================================================

        if plan.target is None:
            # An anaphoric file reference (e.g. "the latest
            # PDF", "the file I worked on") is intentionally
            # resolved at runtime by the session binder /
            # entity history. The executor should not reject
            # it as "missing_target" — instead, accept the
            # plan and mark the result as
            # `requires_runtime_resolution=True` so the
            # caller knows the target will be filled in
            # before the real OS call. Without this
            # exception, every anaphoric L3 decision fails
            # the executor's pre-dispatch check.
            #
            # GUI typing/pasting is the same shape: "type
            # Hello from Genesis" carries target=None because
            # the executor types into whichever window
            # currently has focus. The plan is structurally
            # valid when operation is gui.type_text /
            # gui.paste_text and parameters carry the text.
            params = plan.parameters or {}
            from genesis_os.security_model import assess_operation_risk
            early_assessment = assess_operation_risk(plan.operation)
            # 2026-10-08: the `and not bool(params.get("confirmed", False))`
            # escape is GONE. A plan with no target (anaphoric "the latest
            # PDF", or GUI typing into whatever has focus) could previously
            # satisfy this gate by setting `confirmed=True` in its own
            # parameters -- a self-approval the caller manufactured. The
            # gate is now unconditional, which is the fail-closed
            # direction. gui.type_text / gui.paste_text are unaffected:
            # assess_operation_risk does not require confirmation for
            # them, which was verified before making this change.
            if early_assessment.requires_confirmation:
                return ActionResult.failure_result(
                    operation=plan.operation,
                    target=plan.target,
                    application=plan.application,
                    message="This action requires explicit confirmation before execution.",
                    status="confirmation_required",
                    error=early_assessment.reason,
                    executed=False,
                    verified=False,
                    plan=plan.to_dict(),
                    metadata={
                        "executor_version": self.VERSION,
                        "execution_contract": self.EXECUTION_CONTRACT,
                        "execution_stage": "confirmation",
                        "confirmation_required": True,
                        "security_assessment": {
                            "risk_level": early_assessment.risk_level.value,
                            "requires_confirmation": True,
                            "requires_verification": early_assessment.requires_verification,
                            "reason": early_assessment.reason,
                        },
                    },
                )
            if (
                params.get("source_is_anaphoric")
                or params.get("requires_runtime_resolution")
            ):
                return ActionResult(
                    success=False,
                    operation=plan.operation,
                    target=None,
                    application=plan.application,
                    status="requires_runtime_resolution",
                    message=(
                        "The plan has an anaphoric target "
                        "reference; the runtime entity binder "
                        "must resolve the specific target "
                        "before execution. The plan is "
                        "structurally valid."
                    ),
                    executed=False,
                    verified=False,
                    plan=plan.to_dict(),
                    metadata={
                        "anaphoric_target_pending": True,
                    },
                )
            # Item 20A (S14): the blast-radius grant gate used to live
            # only at the bottom of `execute`, and every target=None
            # path returned before reaching it -- so a Tier 1 targetless
            # operation (file.search / document.* / spreadsheet.read
            # against an outside path) dispatched with NO grant at all.
            # The gate now runs here too, before anything dispatches.
            # For the gui.* operations below it is a no-op: they are
            # Tier 2 when classified from the plan alone.
            denial = self._authorization_gate(plan)
            if denial is not None:
                return denial
            # gui.type_text / gui.paste_text with target=None
            # means "type into focused window" — structurally
            # valid, but the dispatch MUST actually run.
            #
            # Phase 0 forensic finding: returning
            # ``requires_runtime_resolution`` here used to be
            # converted to ``verified=True`` by the workflow
            # engine's carve-out, producing "1 verified step(s)"
            # without ever calling ``pyautogui.typewrite``.
            # This is the production-critical correctness bug.
            #
            # The new contract: even when no explicit window is
            # named, the executor MUST observe the foreground
            # window via user32, refuse unsafe targets, dispatch
            # through the OSManager GUI bridge, and re-inspect
            # the foreground window after dispatch to confirm
            # focus was retained. ``verified`` is bound to the
            # post-state observation, not to "no exception
            # raised".
            #
            # The integrated dispatch lives in
            # ``RuntimeFocusResolver.dispatch_text_or_paste``
            # and is the only legitimate path that may return
            # ``verified=True`` for an implicit-target GUI
            # text-input action.
            if plan.operation in (
                "gui.type_text", "gui.paste_text",
            ) and params.get("text"):
                focus_pattern = (
                    params.get("focus_title_pattern")
                    or params.get("runtime_focus_target")
                    or params.get("target_window")
                )
                # Named-target path: dispatch through the
                # OSManager GUI bridge as before, then let the
                # normalize step derive verified from the
                # provider's own verification result.
                if focus_pattern:
                    try:
                        raw_result = self._dispatch(plan)
                    except Exception as error:
                        friendly = explain_error(
                            error,
                            context={
                                "operation": plan.operation,
                                "target": plan.target,
                                "application": plan.application,
                            },
                        )
                        return ActionResult.failure_result(
                            operation=plan.operation,
                            target=plan.target,
                            application=plan.application,
                            message=friendly.user_message,
                            status="execution_exception",
                            error=friendly.original_error,
                            executed=False,
                            verified=False,
                            plan=plan.to_dict(),
                            metadata={
                                "executor_version": self.VERSION,
                                "execution_contract": (
                                    self.EXECUTION_CONTRACT
                                ),
                                "execution_stage": "dispatch",
                            },
                        )
                    return self._enforce_execution_contract(
                        self._normalize_result(plan, raw_result)
                    )
                # Implicit-target (focused-window) path: the
                # resolver performs the closed-loop dispatch
                # (resolve → safety check → dispatch →
                # verify focus retained) and returns an
                # ``ActionResult`` whose ``verified`` flag is
                # bound to the actual post-state observation.
                #
                # Critically: a target that cannot be safely
                # resolved returns ``unresolved_target`` with
                # ``verified=False``. There is NO path that
                # produces ``verified=True`` without real
                # dispatch and real post-state verification.
                return self._dispatch_gui_text_input(
                    plan,
                    params,
                )
            # gui.click / gui.double_click / gui.scroll /
            # gui.keyboard_action with target=None means "operate
            # on the currently focused window". These operations do
            # not carry a text payload the way type_text / paste_text
            # do, but the same closed-loop safety contract applies:
            # if the runtime focus resolver cannot identify a safe
            # focused window the executor must surface
            # ``unresolved_target`` with ``verified=False`` rather
            # than dispatching into an unknown window.
            if plan.operation in (
                "gui.click", "gui.double_click",
                "gui.scroll", "gui.keyboard_action",
            ):
                return self._dispatch_gui_focus_only(plan, params)
            if plan.operation in ActionPlan.TARGETLESS_OPERATIONS:
                try:
                    raw_result = self._dispatch(plan)
                except Exception as exc:
                    return ActionResult.failure_result(
                        operation=plan.operation,
                        target=None,
                        application=plan.application,
                        message=str(exc),
                        status="execution_exception",
                        error=str(exc),
                        executed=False,
                        verified=False,
                        plan=plan.to_dict(),
                        metadata={
                            "executor_version": self.VERSION,
                            "execution_contract": self.EXECUTION_CONTRACT,
                            "execution_stage": "dispatch",
                        },
                    )
                return self._enforce_execution_contract(
                    self._normalize_result(plan, raw_result)
                )
            return ActionResult.failure_result(
                operation=plan.operation,
                target=None,
                application=plan.application,
                message=(
                    "Genesis could not execute the "
                    "action because no target was "
                    "provided."
                ),
                status="missing_target",
                error="Action target is required.",
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": (
                        self.EXECUTION_CONTRACT
                    ),
                    "validation_stage": "target",
                },
            )

        if (
            isinstance(plan.target, str)
            and not plan.target.strip()
        ):
            # An anaphoric document reference (e.g. "this
            # PDF", "this document") returns an empty target
            # because the runtime entity binder must fill
            # in the actual file. The plan is structurally
            # valid; defer to the runtime instead of
            # rejecting it.
            params = plan.parameters or {}
            if (
                params.get("source_is_anaphoric")
                or params.get("anaphoric_target")
                or params.get("requires_runtime_resolution")
            ):
                return ActionResult(
                    success=False,
                    operation=plan.operation,
                    target=None,
                    application=plan.application,
                    status="requires_runtime_resolution",
                    message=(
                        "The plan has an anaphoric target "
                        "reference; the runtime entity binder "
                        "must resolve the specific target "
                        "before execution. The plan is "
                        "structurally valid."
                    ),
                    executed=False,
                    verified=False,
                    plan=plan.to_dict(),
                    metadata={
                        "anaphoric_target_pending": True,
                    },
                )
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    "Genesis could not execute the "
                    "action because the target is empty."
                ),
                status="invalid_plan",
                error="Action target cannot be empty.",
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": (
                        self.EXECUTION_CONTRACT
                    ),
                    "validation_stage": "target",
                },
            )

        # =====================================================
        # 4. EXECUTION SAFETY
        # =====================================================

        safety_decision = (
            ExecutionSafety.check(
                plan.operation
            )
        )

        # -----------------------------------------------------
        # Invalid operation
        # -----------------------------------------------------

        if safety_decision.status == "invalid":
            return self._invalid_plan_result(
                plan,
                safety_decision.reason,
                stage="safety",
                safety_decision=safety_decision,
            )

        # -----------------------------------------------------
        # Denied / unknown
        # -----------------------------------------------------

        if not safety_decision.allowed:
            return self._safety_blocked_result(
                plan,
                safety_decision,
            )

        # =====================================================
        # 5. CONFIRMATION GATE
        #
        # Safety policy may allow a capability while still
        # requiring explicit user confirmation for mutation.
        # This is deliberately checked after safety and before
        # any OS call.
        # =====================================================

        # Use security model for comprehensive confirmation checking.
        # For browser.click, fetch the target element's real text
        # content from the browser BEFORE dispatch to enable the
        # heuristic signal-word check. This is a lightweight safety
        # net — Phase 8 Browser Intelligence provides real
        # post-state verification and extended heuristic coverage.
        from genesis_os.security_model import assess_operation_risk

        # Build context from plan parameters for operations that
        # support heuristic risk assessment
        security_context = {}
        if plan.operation == "browser.click":
            # First check if element_text is already in parameters
            params = plan.parameters or {}
            if params.get("element_text"):
                security_context["element_text"] = params["element_text"]
            if params.get("aria_label"):
                security_context["aria_label"] = params["aria_label"]
            if params.get("alt_text"):
                security_context["alt_text"] = params["alt_text"]
            
            # If not in parameters, fetch from browser
            if not security_context and self.os_manager:
                selector = params.get("selector") or plan.target
                if selector:
                    try:
                        browser = getattr(self.os_manager, "browser", None)
                        if browser:
                            # Try to extract text from the target element
                            extract_result = browser.extract_text(
                                selector,
                                params.get("session_id", "default"),
                            )
                            if extract_result.get("success"):
                                element_text = extract_result.get("text", "")
                                if element_text:
                                    security_context["element_text"] = element_text
                                else:
                                    # No inner text — could be an image/icon
                                    # or dynamic content.  Try to get alt-text
                                    # and aria-label from the element.
                                    security_context["_no_element_text"] = True
                                    try:
                                        page = browser._get_page()
                                        loc = page.locator(selector)
                                        if loc.count() > 0:
                                            alt = loc.first.get_attribute("alt") or ""
                                            aria = loc.first.get_attribute("aria-label") or ""
                                            if alt:
                                                security_context["alt_text"] = alt
                                            if aria:
                                                security_context["aria_label"] = aria
                                    except Exception:
                                        pass
                    except Exception as exc:
                        # If we can't fetch element text, proceed without it
                        # The heuristic will use the no-text fallback.
                        logger.debug(
                            "browser.click element-text extraction failed "
                            "(selector=%s, session=%s): %s",
                            selector,
                            params.get("session_id", "default"),
                            exc,
                        )
                        pass

        # NOTE (2026-10-15): `security_context` is built above and consumed by
        # the authorization gate below. It used to be handed to
        # `assess_operation_risk(...)` whose result was assigned to
        # `assessment` and never read -- the browser.click risk
        # escalation was therefore computed and discarded. Tier is decided
        # by blast_radius, which deliberately does NOT consult risk_level,
        # so the dead call has been removed rather than resurrected.
        #
        # =========================================================
        # BLAST-RADIUS GATE — HISTORY (this gate IS enabled; see below)
        # =========================================================
        # CORRECTED (Item 14G, S10). This block previously described the gate
        # below as built and proven but NOT enabled, and went on to tell
        # the reader that `confirmed: true` remained the live executor
        # gate and that this branch should not be read as protection.
        # Every clause of that was stale, and it sat directly above the
        # live branch, so it read as the description of it. A reader
        # auditing the Tier 1 path would have been told the executor's
        # grant gate is inert -- the opposite of the truth. The code
        # underneath never changed; only the description did.
        #
        # The accurate history, kept because it explains why the gate
        # is shaped the way it is:
        #
        # The blast-radius gate was originally built and then reverted
        # to inert, because ActionPlan.operation for browser
        # capabilities is the BARE VERB ("wait", "click", "screenshot",
        # "select", "download", "verify"), not "browser.wait". Those
        # verbs match no registered capability's operation field, so the
        # deny-by-default fallback in the resolver gated 31 legitimate
        # Tier 2 browser capabilities.
        #
        # It was NOT fixed by weakening deny-by-default -- that would
        # have reopened the exact coverage gap that fallback closed. It
        # was fixed by having the adapter carry `capability_id` on the
        # plan and having the resolver take the most restrictive of
        # (operation, capability_id), so a missing or wrong
        # capability_id can only make a plan MORE gated. That is
        # fail-safe by construction, which is why the gate is on now.
        #
        # WHAT IS TRUE RIGHT NOW, in this file:
        #
        #   * The blast-radius gate below is LIVE and is the executor's
        #     Tier 1 gate.
        #   * It reads blast_radius ONLY -- never risk_level, which
        #     answers "how scary" rather than "can it be taken back"
        #     and disagrees with blast radius on 57 capabilities by
        #     design.
        #   * `confirmed: true` is NOT an executor gate and must not be
        #     read as one. It is not evidence of anything.
        #   * The AuthorizationGrant channel is proven end to end and
        #     the executor-side switch IS thrown.
        #
        # =========================================================

        # =========================================================
        # BLAST-RADIUS AUTHORIZATION GATE (ENABLED)
        # =========================================================
        # The single source of truth for "is this Tier 1", shared with
        # the adapter. Reads blast_radius only — never risk_level, which
        # answers "how scary" rather than "can it be taken back" and
        # disagrees with blast radius on 57 capabilities by design.
        #
        # Replaces the risk-profile check that used to gate here. The
        # old `security_model.requires_confirmation` gate is retained
        # BELOW for the operations blast radius cannot classify, so this
        # narrows nothing and adds no ungated surface.
        #
        # Enabled after resolving the browser-verb gap: `capability_id`
        # is carried on the plan by the adapter, and the resolver takes
        # the most restrictive of (operation, capability_id), so a
        # missing capability_id can only make a plan MORE gated.
        #
        # Item 20A (S14): the gate body moved into
        # `_authorization_gate`, which reconciles the approved arguments
        # with the ones `_dispatch` will read. It is also called on the
        # `target is None` dispatch paths, which previously returned
        # before this point and dispatched ungated.
        denial = self._authorization_gate(
            plan,
            security_context if security_context else None,
        )
        if denial is not None:
            return denial

        if not _resolved_capability(
            plan.operation, getattr(plan, "capability_id", None)
        ):
            # REPLACED 2026-10-08. This used to read
            # ``plan.parameters["confirmed"]`` and let that boolean
            # decide. That was the original F5 defect: the flag carried
            # no evidence of a human decision and could be set by any
            # caller. The flag is no longer an authority here.
            #
            # Trace that drove the replacement: of the eight operations
            # in ``ActionPlan.KNOWN_DENIED_OPERATIONS`` -- the escape
            # hatch that lets a plan be constructed for an operation with
            # no registered capability -- six have no registry entry at
            # all (``filesystem.delete``, ``filesystem.move``,
            # ``filesystem.rename``, ``process.kill``,
            # ``shell.execute``, ``system.sleep``). Deny-by-default
            # already classifies every one of them as
            # ``irreversible_or_outward``, so the blast-radius grant
            # gate above has already refused the call by the time it
            # arrives here.
            #
            # The old stand-in was therefore doing real work in exactly
            # one case: refusing those six even when a genuine grant was
            # present. Rather than keep a forgeable flag to express
            # "permanently denied", the deny list is now consulted
            # directly. This is strictly STRONGER: an explicitly denied
            # operation cannot be enabled by a flag OR by a grant.
            #
            # Any other operation the resolver cannot identify is left
            # alone here, because blast radius has already required a
            # genuine ``AuthorizationGrant`` for it above. Treating an
            # unidentified capability as Tier 1 and grantable is the
            # documented policy; re-implementing that here would be the
            # second source of truth this work removed.
            from genesis_os.action_plan import KNOWN_DENIED_OPERATIONS

            if plan.operation in KNOWN_DENIED_OPERATIONS:
                return ActionResult.failure_result(
                    operation=plan.operation,
                    target=plan.target,
                    application=plan.application,
                    message=(
                        "This operation is denied by policy and cannot be "
                        "approved."
                    ),
                    status="confirmation_required",
                    error=(
                        f"{plan.operation} is in the denied-operation set "
                        f"and has no registered capability; it cannot be "
                        f"authorised by a grant or a confirmation flag."
                    ),
                    executed=False,
                    verified=False,
                    plan=plan.to_dict(),
                    metadata={
                        "executor_version": self.VERSION,
                        "execution_contract": self.EXECUTION_CONTRACT,
                        "execution_stage": "denied",
                        "denied_operation": True,
                        "confirmation_required": True,
                    },
                )

        # =====================================================
        # 6. FINAL ACTION PLAN VALIDATION
        #
        # At this point safety has already approved the
        # operation.
        # =====================================================

        try:
            # GUI typing/pasting operations can carry an empty
            # target — the executor types into whatever window
            # currently has focus when the user did not name
            # one ("type Hello from Genesis"). Skip the
            # require_target gate for gui.* operations.
            gui_ops = {
                "gui.type_text", "gui.paste_text",
                "gui.focus_window", "gui.inspect_window",
                "gui.click", "gui.double_click",
                "gui.select", "gui.scroll",
                "gui.read_visible_text",
                "gui.keyboard_action",
                "gui.hotkey", "gui.drag",
                "gui.wait", "gui.wait_for_window",
                "gui.inspect_ui_tree",
            }
            require_target_for_plan = (
                plan.operation not in gui_ops
            )
            plan.validate(
                supported_operations=(
                    self.SUPPORTED_OPERATIONS
                ),
                require_target=require_target_for_plan,
                minimum_confidence=(
                    self.MINIMUM_CONFIDENCE
                ),
            )

            # Phase 1 contract: the validated plan must also satisfy
            # the Task boundary before dispatch.
            TaskContract.from_action_plan(plan)

        except (
            ActionPlanValidationError,
            ValueError,
            TypeError,
        ) as error:
            return self._invalid_plan_result(
                plan,
                str(error),
                stage="plan",
            )

        # =====================================================
        # 7. DISPATCH
        # =====================================================

        # Item 21A (C32): this used to be
        #
        #     with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _executor:
        #         _future = _executor.submit(self._dispatch, plan)
        #         raw_result = _future.result(timeout=timeout)
        #
        # The `with` form made the per-action timeout unenforceable:
        # future.result DID raise TimeoutError at `timeout`, but
        # leaving the block then ran ThreadPoolExecutor.__exit__ ->
        # shutdown(wait=True), which waits for the hung _dispatch to
        # finish. Measured on the committed original: a 3.0s sleep
        # against a 0.5s budget returned at 3.02s -- the timeout
        # fired on paper and the caller paid the entire overrun.
        #
        # The executor is now built explicitly (Item 17A's shape) and
        # BOTH failure paths shut it down without waiting, so the
        # CALL returns promptly.
        #
        # THE HONEST LIMIT, stated rather than hidden: wait=False does
        # not kill anything. The worker running _dispatch cannot be
        # interrupted, so on timeout it is ABANDONED -- still running,
        # still holding whatever it holds, until _dispatch returns on
        # its own. Nothing here claims the action was stopped; only
        # that the caller is no longer blocked behind it. The same
        # word lives in execute's docstring because the test reads
        # this function via AST and ast.unparse drops comments.
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            _future = _executor.submit(self._dispatch, plan)
            raw_result = _future.result(timeout=timeout)

        except concurrent.futures.TimeoutError:
            _executor.shutdown(wait=False, cancel_futures=True)
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    f"Execution exceeded the {timeout}s timeout."
                ),
                status="execution_timeout",
                error="TimeoutError",
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "execution_stage": "dispatch",
                    "timeout_seconds": timeout,
                },
            )

        except Exception as error:
            _executor.shutdown(wait=False, cancel_futures=True)
            friendly = explain_error(
                error,
                context={
                    "operation": plan.operation,
                    "target": plan.target,
                    "application": plan.application,
                },
            )
            return self._enforce_execution_contract(
                ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=friendly.user_message,
                status="execution_exception",
                error=friendly.original_error,
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": (
                        self.EXECUTION_CONTRACT
                    ),
                    "execution_stage": "dispatch",
                    "friendly_error": {
                        "user_message": friendly.user_message,
                        "suggested_actions": friendly.suggested_actions,
                        "recovery_hint": friendly.recovery_hint,
                    },
                },
            )
        )

        else:
            # Runs only when neither return above did: the healthy
            # path joins its worker. The returns sit in the except
            # blocks, never inside `try`, so `else` is reachable
            # here (a return inside `try` would skip `else` and leak
            # one worker thread per healthy dispatch -- the trap
            # Item 17A pinned with a spy executor; this file's
            # test_a_successful_dispatch_still_joins_its_worker pins
            # it for the per-action path).
            _executor.shutdown(wait=True)

        # =====================================================
        # 8. NORMALIZATION
        # =====================================================

        return self._enforce_execution_contract(
            self._normalize_result(
                plan,
                raw_result,
            )
        )

    # =========================================================
    # PHASE 1 CONTRACT ENFORCEMENT
    # =========================================================

    @staticmethod
    def _enforce_execution_contract(
        result: ActionResult,
    ) -> ActionResult:
        ExecutionContract.from_action_result(result)
        try:
            evidence = EvidenceContract.from_result(result)
            require_result_evidence(result, evidence=evidence)
            result.metadata["evidence_contract"] = evidence.to_dict()
        except ContractViolationError as error:
            result.verified = False
            result.already_in_desired_state = False
            result.status = "verification_unavailable"
            result.metadata["verification_evidence_rejected"] = str(error)
            result.metadata["trustworthy_success"] = False
        return result

    # =========================================================
    # STRUCTURAL VALIDATION
    # =========================================================

    @staticmethod
    def _validate_structure(
        plan: ActionPlan,
    ) -> str | None:
        """
        Validate fields required before safety evaluation.
        """

        if not isinstance(
            plan.operation,
            str,
        ):
            return (
                "Action operation must be a string."
            )

        if not plan.operation.strip():
            return (
                "Action operation cannot be empty."
            )

        if (
            plan.target is not None
            and not isinstance(
                plan.target,
                str,
            )
        ):
            return (
                "Action target must be a string or None."
            )

        confidence = plan.confidence

        if isinstance(
            confidence,
            bool,
        ):
            return (
                "Action confidence must be numeric."
            )

        if not isinstance(
            confidence,
            (int, float),
        ):
            return (
                "Action confidence must be numeric."
            )

        return None

    # =========================================================
    # INVALID PLAN
    # =========================================================

    def _invalid_plan_result(
        self,
        plan: ActionPlan,
        error: str,
        *,
        stage: str,
        safety_decision: SafetyDecision | None = None,
    ) -> ActionResult:
        metadata = {
            "executor_version": self.VERSION,
            "execution_contract": (
                self.EXECUTION_CONTRACT
            ),
            "validation_stage": stage,
            "validation_error": error,
        }

        if safety_decision is not None:
            metadata.update(
                {
                    "safety_decision": (
                        safety_decision.to_dict()
                    ),
                    "safety_status": (
                        safety_decision.status
                    ),
                    "safety_reason": (
                        safety_decision.reason
                    ),
                }
            )

        return ActionResult.failure_result(
            operation=(
                plan.operation
                if isinstance(
                    plan.operation,
                    str,
                )
                else "unknown"
            ),
            target=plan.target,
            application=plan.application,
            message=(
                "Genesis rejected the action "
                "because the action plan is invalid."
            ),
            status="invalid_plan",
            error=error,
            executed=False,
            verified=False,
            plan=plan.to_dict(),
            metadata=metadata,
        )

    # =========================================================
    # SAFETY BLOCK
    # =========================================================

    def _safety_blocked_result(
        self,
        plan: ActionPlan,
        decision: SafetyDecision,
    ) -> ActionResult:
        """
        Create a deterministic safety-block result.

        The operation has NOT been executed.
        """

        reason = decision.reason

        return ActionResult.failure_result(
            operation=plan.operation,
            target=plan.target,
            application=plan.application,
            message=(
                "Genesis blocked the requested action "
                "because it is not permitted by the "
                "execution safety policy."
            ),
            status="safety_blocked",
            error=(
                "Execution blocked by safety policy: "
                f"{reason}"
            ),
            executed=False,
            verified=False,
            plan=plan.to_dict(),
            metadata={
                "executor_version": self.VERSION,
                "execution_contract": (
                    self.EXECUTION_CONTRACT
                ),
                "execution_stage": "safety",
                "safety_decision": (
                    decision.to_dict()
                ),
                "safety_status": (
                    decision.status
                ),
                "safety_reason": reason,
            },
        )

    # =========================================================
    # CONFIRMATION REQUIRED
    # =========================================================

    def _confirmation_required_result(self, plan, capability):
        message = (
            "This action changes the computer or its data and "
            "requires explicit confirmation before execution."
        )
        return ActionResult.failure_result(
            operation=plan.operation, target=plan.target, application=plan.application,
            message=message, status="confirmation_required",
            error=message, executed=False, verified=False, plan=plan.to_dict(),
            metadata={
                "executor_version": self.VERSION,
                "execution_contract": self.EXECUTION_CONTRACT,
                "execution_stage": "confirmation",
                "confirmation_required": True,
                "capability": capability.to_dict(),
            },
        )

    # =========================================================
    # DISPATCH
    # =========================================================

    # -----------------------------------------------------
    # GUI text input: closed-loop dispatch + verification.
    # -----------------------------------------------------
    #
    # This is the only legitimate path that may produce a
    # ``verified=True`` outcome for ``gui.type_text`` or
    # ``gui.paste_text`` when the user did not name a target
    # window.
    #
    # The integrated resolver performs:
    #
    #     1. observe the current OS foreground window via user32
    #     2. refuse unsafe targets (console, REPL, no-title)
    #     3. dispatch through ``os_manager.gui_action`` so the
    #        underlying ``pyautogui.typewrite`` /
    #        ``pyperclip.copy`` + ``hotkey("ctrl","v")`` actually
    #        runs against the focused window
    #     4. re-inspect the foreground window after dispatch
    #        and confirm the same window is still focused
    #
    # ``verified`` is bound to step 4's observation, not to
    # "no exception was raised". When the resolver cannot
    # safely identify a target the executor returns an
    # ``unresolved_target`` failure (``success=False``,
    # ``executed=False``, ``verified=False``) so the workflow
    # engine cannot mistakenly treat the request as completed.
    #
    # The previous behaviour at this site returned
    # ``requires_runtime_resolution`` which the workflow
    # engine's carve-out then converted to
    # ``verified=True`` — the Phase 0 production-critical bug.

    def _dispatch_gui_text_input(
        self,
        plan: "ActionPlan",
        params: Dict[str, Any],
    ) -> ActionResult:
        text = params.get("text") or ""
        action = (
            "type_text"
            if plan.operation == "gui.type_text"
            else "paste_text"
        )

        resolver = RuntimeFocusResolver()
        outcome: RuntimeFocusResolution = (
            resolver.dispatch_text_or_paste(
                os_manager=self.os_manager,
                action=action,
                text=text,
                focus_title_pattern=None,
                focus_timeout=float(
                    params.get("focus_timeout", 3.0)
                ),
                focus_poll_interval=float(
                    params.get("focus_poll_interval", 0.2)
                ),
                text_parameter_key="text",
                require_focus_retain=True,
            )
        )

        # --------------------------------------------------
        # Unresolved target — no safe window to type into.
        # The action was NOT executed. ``verified`` stays
        # False so the workflow engine cannot promote this
        # step to ``completed``.
        # --------------------------------------------------
        if (
            not outcome.dispatched
            or outcome.status == "unresolved_target"
        ):
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    outcome.error
                    or (
                        "Genesis could not safely resolve a "
                        "focused window for "
                        f"{plan.operation}."
                    )
                ),
                status=outcome.status or "unresolved_target",
                error=outcome.error,
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "validation_stage": "runtime_focus_resolution",
                    "safety_rejected": outcome.safety_rejected,
                    "safety_reason": outcome.safety_reason,
                    "focused_window": (
                        {
                            "hwnd": outcome.focused.hwnd,
                            "title": outcome.focused.title,
                            "pid": outcome.focused.pid,
                        }
                        if outcome.focused is not None
                        else None
                    ),
                },
            )

        # --------------------------------------------------
        # Dispatched but post-state verification failed.
        # The keystroke ran but the foreground window
        # changed during the call, so the typed text may
        # have landed in the wrong window. This is NOT a
        # verified success; the runtime surface remains
        # ``verification_failed`` with ``verified=False``.
        # --------------------------------------------------
        if not outcome.verified:
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    outcome.error
                    or (
                        f"{plan.operation} dispatched but the "
                        "foreground window changed during the "
                        "call; verification could not be "
                        "confirmed."
                    )
                ),
                status=(
                    outcome.status or "verification_failed"
                ),
                error=outcome.error,
                executed=True,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "validation_stage": "runtime_focus_resolution",
                    "focused_window": (
                        {
                            "hwnd": outcome.focused.hwnd,
                            "title": outcome.focused.title,
                            "pid": outcome.focused.pid,
                        }
                        if outcome.focused is not None
                        else None
                    ),
                },
            )

        # --------------------------------------------------
        # Dispatched AND verified. The only branch that
        # may legitimately return ``verified=True``.
        # --------------------------------------------------

        # --------------------------------------------------
        # CONTENT VERIFICATION: After dispatch and focus
        # retention are confirmed, attempt to read the
        # focused element's content via UIA ValuePattern
        # to verify the expected text was actually inserted.
        # This is the independent observation that separates
        # DISPATCH_CONFIRMED from CONTENT_VERIFIED.
        # --------------------------------------------------
        content_verification: Dict[str, Any] = {
            "content_read": False,
            "content_method": "none",
            "content_observed": "",
        }
        try:
            gui = getattr(self.os_manager, "gui", None)
            if gui is not None:
                read_result = gui.read_focused_text()
                if isinstance(read_result, dict):
                    read_success = bool(read_result.get("success"))
                    read_data = read_result.get("data")
                else:
                    read_success = bool(getattr(read_result, "success", False))
                    read_data = getattr(read_result, "data", None)
                if read_success and isinstance(read_data, dict):
                    data = read_data
                    observed_text = data.get("text", "")
                    readable = data.get("readable", False)
                    method = data.get("method", "none")
                    raw_data = (
                        outcome.raw_result.get("data")
                        if isinstance(outcome.raw_result, dict)
                        else {}
                    )
                    expected_observed = str(
                        (raw_data or {}).get("observed_text", "")
                    )
                    content_verification = {
                        "content_read": readable,
                        "content_match": bool(
                            data.get("content_match", False)
                            or (
                                expected_observed
                                and expected_observed in str(observed_text)
                            )
                        ),
                        "content_method": method,
                        "content_observed": str(observed_text)[:2000],
                        "content_length": len(str(observed_text)),
                        "content_truncated": len(str(observed_text)) > 2000,
                    }
        except Exception:
            pass

        content_verified = bool(
            content_verification.get("content_read")
            and content_verification.get("content_match")
        )
        raw_payload: Dict[str, Any] = {
            "success": True,
            "operation": plan.operation,
            "executed": True,
            "verified": content_verified,
            "message": (
                outcome.raw_result.get("message")
                if isinstance(outcome.raw_result, dict)
                else (
                    f"Typed {len(text)} character(s) into the "
                    f"focused window." if action == "type_text"
                    else f"Pasted {len(text)} character(s) into the focused window."
                )
            ),
            "data": (
                dict(outcome.raw_result.get("data") or {})
                if isinstance(outcome.raw_result, dict)
                else {}
            ),
            "metadata": (
                dict(outcome.raw_result.get("metadata") or {})
                if isinstance(outcome.raw_result, dict)
                else {}
            ),
            "focused_window": (
                {
                    "hwnd": outcome.focused.hwnd,
                    "title": outcome.focused.title,
                    "pid": outcome.focused.pid,
                }
                if outcome.focused is not None
                else None
            ),
            "verification_type": (
                "content_verified"
                if content_verified
                else "content_unverified"
            ),
            "verification_reason": (
                "Focused content readback matched the dispatched text."
                if content_verified
                else "Focused content could not be independently read back and matched."
            ),
            "content_verification": content_verification,
        }
        return self._enforce_execution_contract(
            self._normalize_result(plan, raw_payload)
        )

    # -----------------------------------------------------
    # GUI focus-only dispatch: click / double_click / scroll /
    # keyboard_action.
    # -----------------------------------------------------
    #
    # These operations do not carry a text payload the way
    # ``type_text`` / ``paste_text`` do, but the same closed-loop
    # safety contract applies: if the runtime focus resolver cannot
    # identify a safe focused window the executor MUST surface
    # ``unresolved_target`` with ``verified=False`` rather than
    # dispatching into an unknown target.
    #
    # When a safe focused window IS resolved the executor performs
    # the requested dispatch (``pyautogui.click`` / ``scroll`` /
    # ``hotkey``) and re-inspects the foreground window afterwards.
    # The post-state observation binds ``verified`` to a real
    # signal -- the same focus-retained contract ``type_text`` uses
    # -- so the workflow engine cannot promote an unverified
    # dispatch to ``completed``.

    def _dispatch_gui_focus_only(
        self,
        plan: "ActionPlan",
        params: Dict[str, Any],
    ) -> ActionResult:
        op_to_action = {
            "gui.click": "click",
            "gui.double_click": "double_click",
            "gui.scroll": "scroll",
            "gui.keyboard_action": "keyboard_action",
        }
        action = op_to_action[plan.operation]

        # 1. Resolve the focused window via the same runtime focus
        #    resolver used for text input. This is the safety gate
        #    -- it refuses to dispatch into a console / REPL / no
        #    -title window before any GUI bridge call is made.
        user32 = None
        try:
            gui = getattr(self.os_manager, "gui", None)
            if gui is not None:
                provider = getattr(gui, "_provider", None)
                if provider is not None:
                    user32 = getattr(provider, "_user32", None)
        except Exception:
            user32 = None

        resolver = RuntimeFocusResolver()
        if user32 is not None and hasattr(user32, "GetForegroundWindow"):
            focused = resolver.resolve_focused_window(user32)
        else:
            focused = None

        if focused is None:
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    "No foreground window is currently focused; "
                    f"refusing to dispatch {plan.operation} into "
                    "an unknown target."
                ),
                status="unresolved_target",
                error="no foreground window",
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "validation_stage": "runtime_focus_resolution",
                },
            )

        safe, reason = resolver.is_safe_target(focused.hwnd, focused.title)
        if not safe:
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    f"Refusing to dispatch {plan.operation} into "
                    f"unsafe window ({reason}); status=unresolved_target."
                ),
                status="unresolved_target",
                error=reason,
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "validation_stage": "runtime_focus_resolution",
                    "safety_rejected": True,
                    "safety_reason": reason,
                    "focused_window": {
                        "hwnd": focused.hwnd,
                        "title": focused.title,
                        "pid": focused.pid,
                    },
                },
            )

        # 2. Dispatch through the OSManager GUI bridge.
        try:
            if plan.operation == "gui.click":
                raw = self.os_manager.gui_action(
                    "click", x=params.get("x", 0), y=params.get("y", 0)
                )
            elif plan.operation == "gui.double_click":
                raw = self.os_manager.gui_action(
                    "double_click", x=params.get("x", 0), y=params.get("y", 0)
                )
            elif plan.operation == "gui.scroll":
                raw = self.os_manager.gui_action(
                    "scroll",
                    direction=params.get("direction", "down"),
                    amount=params.get("amount", 3),
                )
            elif plan.operation == "gui.keyboard_action":
                raw = self.os_manager.gui_action(
                    "keyboard_action", key=params.get("key", "")
                )
            else:  # pragma: no cover - defensive
                raise ValueError(f"Unsupported focus-only op: {plan.operation}")
        except Exception as exc:
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=f"GUI dispatch raised an exception: {exc}",
                status="execution_exception",
                error=str(exc),
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "execution_stage": "dispatch",
                },
            )

        if not isinstance(raw, dict):
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    "OSManager GUI bridge returned a non-dict payload "
                    f"for {plan.operation}."
                ),
                status="invalid_execution_result",
                error="OSManager returned non-dict",
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "normalization_stage": "type",
                },
            )

        dispatched = bool(raw.get("success")) and bool(raw.get("executed", True))
        if not dispatched:
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    raw.get("error")
                    or raw.get("message")
                    or f"{plan.operation} dispatch did not report success."
                ),
                status="execution_failed",
                error=raw.get("error"),
                executed=False,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": self.EXECUTION_CONTRACT,
                    "validation_stage": "runtime_focus_resolution",
                    "focused_window": {
                        "hwnd": focused.hwnd,
                        "title": focused.title,
                        "pid": focused.pid,
                    },
                },
            )

        # 3. Post-state observation: confirm focus was retained.
        #    This is the cheapest real signal we have for
        #    click / scroll / keyboard actions -- if the foreground
        #    window shifted during the dispatch the keystrokes /
        #    mouse moves may have landed in the wrong window.
        retained = resolver.verify_focus_retained(user32, focused.hwnd)
        raw_payload: Dict[str, Any] = dict(raw)
        provider_evidence = bool(
            raw.get("click_postcondition_verified") is True
        )
        raw_payload["verified"] = bool(retained and provider_evidence)
        if raw_payload["verified"]:
            raw_payload["verification_type"] = "capability_post_state"
            raw_payload["verification_reason"] = (
                f"Capability post-state evidence was reported after "
                f"{plan.operation} dispatch."
            )
        else:
            raw_payload["verification_type"] = "unverified_focus_only"
            raw_payload["verification_reason"] = (
                "Focus retention was observed, but no capability-specific "
                "post-state evidence was available."
            )
        raw_payload["focused_window"] = {
            "hwnd": focused.hwnd,
            "title": focused.title,
            "pid": focused.pid,
        }
        return self._enforce_execution_contract(
            self._normalize_result(plan, raw_payload)
        )

    def _dispatch(
        self,
        plan: ActionPlan,
    ) -> Any:
        """
        Dispatch only an already-approved operation.
        """

        op = plan.operation
        op = {
            "document.compare_intel": "document.compare",
            "document.create_docx_intel": "document.create_docx",
            "document.inspect_intel": "document.inspect",
            "document.read_intel": "document.read",
            "document.search_intel": "document.search",
            "document.summarize_intel": "document.summarize",
            "spreadsheet.inspect_intel": "spreadsheet.inspect",
            "spreadsheet.read_intel": "spreadsheet.read",
        }.get(op, op)
        p = plan.parameters
        t = plan.target

        if op == "application.open":
            application = plan.application or t
            file_path = (
                p.get("file_path")
                if p.get("open_file")
                else None
            )
            if file_path:
                return self.os_manager.open_application(
                    application,
                    file_path=file_path,
                )
            return self.os_manager.open_application(application)
        if op == "application.close": return self.os_manager.close_application(t)
        if op == "application.inspect": return self.os_manager.inspect_application(t)
        if op == "application.list": return self.os_manager.list_applications()
        if op == "file.inspect": return self.os_manager.inspect_file(t)
        if op == "file.read": return self.os_manager.read_file(t)
        if op == "file.search": return self.os_manager.search_file(p.get("path", "."), p.get("query", t) or t)
        if op == "filesystem.search": return self.os_manager.search_file(p.get("path", t or "."), p.get("query", "") or "")
        if op == "file.hash": return self.os_manager.hash_file(t, p.get("algorithm", "sha256"))
        if op == "file.open": return self.os_manager.open_file(t)
        if op == "filesystem.open": return self.os_manager.open_file(t)
        if op == "file.watch": return self.os_manager.watch_file(t, p.get("event", "modified"))
        # Item 3B-3b: the OS managers no longer branch on `confirmed`, so the
        # hardcoded `confirmed=True` that used to prop up their internal
        # gates is gone. Authorization is decided ONCE, above, by
        # `_operation_requires_authorization` + a valid AuthorizationGrant.
        if op == "file.create": return self.os_manager.create_file(t, p.get("content", ""), overwrite=bool(p.get("overwrite", False)))
        if op == "file.copy": return self.os_manager.copy_file(p.get("source", t), p.get("destination", t))
        if op == "file.move": return self.os_manager.move_file(p.get("source", t), p.get("destination", t))
        if op == "file.rename": return self.os_manager.rename_file(p.get("source", t), p.get("new_name", t))
        if op == "file.delete": return self.os_manager.delete_file(t)
        if op == "folder.organize": return self.os_manager.organize_folder(t, dry_run=bool(p.get("dry_run", False)))
        if op == "folder.rename": return self.os_manager.rename_folder(t, p.get("new_name", ""))
        if op == "folder.move": return self.os_manager.move_folder(t, p.get("destination"))
        if op == "folder.delete": return self.os_manager.delete_folder(t)
        if op == "folder.inspect": return self.os_manager.inspect_folder(t)
        if op == "folder.open": return self.os_manager.open_folder(t)
        if op == "folder.create": return self.os_manager.create_folder(t)
        if op == "process.list": return self.os_manager.list_processes(None if t in {None, "", "computer"} else t, limit=p.get("limit", 500))
        if op == "process.inspect": return self.os_manager.inspect_process(t)
        if op == "browser.open_url": return self.os_manager.open_url(t)
        if op == "browser.search": return self.os_manager.web_search(p.get("query", t), p.get("engine", "google"))
        if op == "system.status": return self.os_manager.system_status()
        if op == "system.open_settings": return self.os_manager.open_settings(t)
        if op == "network.list_wifi": return self.os_manager.list_wifi()
        if op == "network.connect_wifi": return self.os_manager.connect_wifi(p.get("ssid", t), p.get("password", ""))

        # -----------------------------------------------------
        # LEVEL 3.10 — UNIVERSAL DESKTOP CONTROL
        # -----------------------------------------------------

        if op in ("media.play_pause", "media.next", "media.previous", "media.stop"):
            action = op.split(".", 1)[1]
            return self.os_manager.media_transport(action)
        if op == "volume.up":
            return self.os_manager.volume_step("up", int(p.get("steps", 2)))
        if op == "volume.down":
            return self.os_manager.volume_step("down", int(p.get("steps", 2)))
        if op == "volume.mute_toggle":
            mute = p.get("mute")
            return self.os_manager.volume_mute_toggle(None if mute is None else bool(mute))
        if op == "volume.set":
            return self.os_manager.volume_set(p.get("percent", t))
        if op == "volume.get":
            return self.os_manager.volume_get()
        if op == "display.brightness_set":
            direction = p.get("direction")
            percent = p.get("percent") if direction is None else None
            if percent is None and direction is None:
                raw = p.get("percent", t)
                try:
                    percent = int(str(raw).strip().rstrip("%"))
                except (TypeError, ValueError):
                    percent = None
            return self.os_manager.brightness_set(percent, direction=direction)
        if op == "display.brightness_get":
            return self.os_manager.brightness_get()
        if op == "hardware.battery":
            return self.os_manager.battery_status()
        if op == "hardware.stats":
            return self.os_manager.hardware_stats()
        if op == "clipboard.copy":
            text = p.get("text", t)
            return self.os_manager.clipboard_copy("" if text is None else str(text))
        if op == "clipboard.paste":
            return self.os_manager.clipboard_paste()
        if op == "screen.capture":
            target_path = p.get("path") or (t if (t and str(t) not in {"screen", "screenshot", "display"}) else None)
            return self.os_manager.screenshot(target_path)
        if op == "workstation.lock":
            return self.os_manager.lock_workstation()
        if op == "web.research":
            return self.os_manager.web_research(
                p.get("query", t),
                int(p.get("max_results", 5)),
            )

        # -----------------------------------------------------
        # LEVEL 3.12 — WINDOWS / PRODUCTIVITY / CLEANUP
        # -----------------------------------------------------

        if op == "window.minimize_all":
            return self.os_manager.minimize_all_windows()
        if op == "window.restore":
            return self.os_manager.restore_windows()
        if op == "window.show_desktop":
            return self.os_manager.show_desktop()
        if op in ("web.weather", "weather.current"):
            return self.os_manager.weather(p.get("city", t))
        if op == "time.world_clock":
            return self.os_manager.world_clock(p.get("city", t))
        if op == "math.evaluate":
            return self.os_manager.calculate(p.get("expression", t))
        if op == "hardware.storage":
            return self.os_manager.storage_status()
        if op == "notes.create":
            text = p.get("text", p.get("content", t))
            return self.os_manager.create_note("" if text is None else str(text))
        if op == "notes.list":
            return self.os_manager.list_notes()
        if op == "package.search":
            return self.os_manager.package_search(p.get("query", t), int(p.get("max_results", 5)))
        if op == "package.install":
            return self.os_manager.package_install(p.get("package", t))
        if op == "package.uninstall":
            return self.os_manager.package_uninstall(p.get("package", t))
        if op == "cleanup.recycle_bin_query":
            return self.os_manager.recycle_bin_stats()
        if op == "cleanup.empty_recycle_bin":
            return self.os_manager.empty_recycle_bin()

        # -----------------------------------------------------
        # LEVEL 3.13 — ADVANCED BROWSER INTELLIGENCE
        # -----------------------------------------------------
 
        if op == "browser.click":
            return self.os_manager.browser_click(p.get("selector", t), p.get("session_id", "default"))
        if op == "browser.type":
            return self.os_manager.browser_type(p.get("selector", t), p.get("text", ""), p.get("session_id", "default"))
        if op == "browser.scroll":
            return self.os_manager.browser_scroll(p.get("direction", "down"), int(p.get("amount", 3)), p.get("session_id", "default"))
        if op == "browser.find":
            return self.os_manager.browser_find(p.get("text", t), p.get("session_id", "default"))
        if op == "browser.extract":
            return self.os_manager.browser_extract(p.get("selector"), p.get("session_id", "default"))
        if op == "browser.get_title":
            return self.os_manager.browser_get_title(p.get("session_id", "default"))
        if op == "browser.get_url":
            return self.os_manager.browser_get_url(p.get("session_id", "default"))
        if op == "browser.switch_tab":
            return self.os_manager.browser_switch_tab(int(p.get("index", 0)), p.get("session_id", "default"))
        if op == "browser.open_tab":
            return self.os_manager.browser_open_tab(p.get("url"), p.get("session_id", "default"))
        if op == "browser.close_tab":
            idx = p.get("index")
            return self.os_manager.browser_close_tab(int(idx) if idx is not None else None, p.get("session_id", "default"))
        if op == "browser.get_tabs":
            return self.os_manager.browser_get_tabs(p.get("session_id", "default"))
        if op == "browser.wait":
            return self.os_manager.browser_wait(p.get("selector", t), float(p.get("timeout", 10.0)), p.get("session_id", "default"))
        if op == "browser.screenshot":
            return self.os_manager.browser_screenshot(p.get("path"), p.get("session_id", "default"))
        if op == "browser.verify":
            return self.os_manager.browser_verify(p.get("expected_url"), p.get("expected_title_contains"), p.get("session_id", "default"))
        if op == "browser.capabilities":
            return self.os_manager.browser_capabilities()
        if op == "browser.get_page_state":
            return self.os_manager.browser_get_page_state(p.get("session_id", "default"))
        if op == "browser.find_text":
            return self.os_manager.browser_find(p.get("text", t), p.get("session_id", "default"))
        if op == "browser.select":
            return self.os_manager.browser_select(
                p.get("selector", t),
                value=p.get("value"),
                label=p.get("label"),
                index=int(p["index"]) if p.get("index") is not None else None,
                session_id=p.get("session_id", "default"),
            )
        if op == "browser.download":
            return self.os_manager.browser_download(
                p.get("url", t),
                save_path=p.get("save_path"),
                session_id=p.get("session_id", "default"),
            )
        if op == "browser.upload":
            return self.os_manager.browser_upload(
                p.get("selector", t),
                p.get("file_path", ""),
                session_id=p.get("session_id", "default"),
            )

        # -----------------------------------------------------
        # LEVEL 3.14+ — GUI INTERACTION
        # -----------------------------------------------------

        if op == "gui.focus_window":
            return self.os_manager.gui_action("focus_window", title_pattern=t)
        if op == "gui.inspect_window":
            return self.os_manager.gui_action("inspect_window", title_pattern=t)
        if op == "gui.click":
            return self.os_manager.gui_action("click", x=p.get("x", 0), y=p.get("y", 0))
        if op == "gui.double_click":
            return self.os_manager.gui_action("double_click", x=p.get("x", 0), y=p.get("y", 0))
        if op == "gui.type_text":
            return self.os_manager.gui_action(
                "type_text",
                text=p.get("text", t),
                focus_title_pattern=p.get("focus_title_pattern") or p.get("target_window"),
                focus_timeout=p.get("focus_timeout", 3.0),
                focus_poll_interval=p.get("focus_poll_interval", 0.2),
            )
        if op == "gui.paste_text":
            return self.os_manager.gui_action(
                "paste_text",
                text=p.get("text", t),
                focus_title_pattern=p.get("focus_title_pattern") or p.get("target_window"),
                focus_timeout=p.get("focus_timeout", 3.0),
                focus_poll_interval=p.get("focus_poll_interval", 0.2),
            )
        if op == "gui.read_visible_text":
            return self.os_manager.gui_action("read_visible_text")
        if op == "gui.select":
            return self.os_manager.gui_action("select", start=p.get("start", 0), end=p.get("end", 0))
        if op == "gui.scroll":
            return self.os_manager.gui_action("scroll", direction=p.get("direction", "down"), amount=p.get("amount", 3))
        if op == "gui.keyboard_action":
            return self.os_manager.gui_action("keyboard_action", key=p.get("key", t))

        # -----------------------------------------------------
        # PHASE 6 — EXTENDED GUI INTERACTION
        # -----------------------------------------------------

        if op == "gui.hotkey":
            return self.os_manager.gui_action("hotkey", keys=p.get("keys", t))
        if op == "gui.drag":
            return self.os_manager.gui_action(
                "drag",
                start_x=p.get("start_x", 0),
                start_y=p.get("start_y", 0),
                end_x=p.get("end_x", 0),
                end_y=p.get("end_y", 0),
                duration=p.get("duration", 0.5),
            )
        if op == "gui.wait_for_window":
            return self.os_manager.gui_action(
                "wait_for_window",
                title_pattern=p.get("title_pattern", t),
                timeout=p.get("timeout", 3.0),
                poll_interval=p.get("poll_interval", 0.2),
            )
        if op == "gui.inspect_ui_tree":
            return self.os_manager.gui_action(
                "inspect_ui_tree",
                title_pattern=p.get("title_pattern", t),
            )
        if op == "gui.wait":
            return self.os_manager.gui_action("wait", seconds=float(p.get("seconds", p.get("timeout", 1.0))))
        if op == "gui.wait_for_state":
            return self.os_manager.gui_action(
                "wait_for_state",
                condition=p.get("condition"),
                timeout=float(p.get("timeout", 3.0)),
            )
        if op == "application.focus":
            return self.os_manager.gui_action("focus_window", title_pattern=t)
        if op == "application.inspect_window_content":
            return self.os_manager.gui_action("inspect_window", title_pattern=t)
        if op == "application.window_list":
            from genesis_os.window_models import WindowResolver
            resolver = WindowResolver()
            windows = resolver.enumerate_windows()
            return {
                "success": True,
                "operation": "application.window_list",
                "executed": False,
                "verified": True,
                "windows": [w.to_dict() for w in windows],
                "count": len(windows),
            }

        # -----------------------------------------------------
        # LEVEL 3.14+ — DOCUMENT INTELLIGENCE
        # -----------------------------------------------------

        if op == "document.inspect":
            return self.os_manager.doc_inspect(t)
        if op == "document.read":
            return self.os_manager.doc_read(t)
        if op == "document.search":
            return self.os_manager.doc_search(t, p.get("query", ""))
        # ``document.search_intel`` is the registered capability
        # id for the doc-intel search wrapper (``os_manager.py``).
        # The public alias ``document.search`` is preserved above
        # for backward compatibility with plans built before the
        # id was renamed; both dispatch to the same OSManager
        # method.
        if op == "document.search_intel":
            return self.os_manager.doc_search(t, p.get("query", ""))
        if op == "document.create":
            return self.os_manager.doc_create(t, doc_type=p.get("format", "txt"), title=p.get("title"), content=p.get("content"), sections=p.get("sections"), headers=p.get("headers"), rows=p.get("rows"))
        if op == "document.create_txt":
            return self.os_manager.doc_create(t, doc_type="txt", content=p.get("content", ""))
        if op == "document.create_docx":
            return self.os_manager.doc_create(t, doc_type="docx", title=p.get("title", "Genesis Document"), sections=p.get("sections", []))
        if op == "document.create_csv":
            return self.os_manager.doc_create(t, doc_type="csv", headers=p.get("headers", []), rows=p.get("rows", []))
        if op == "document.create_json":
            return self.os_manager.doc_create(t, doc_type="json", content=p.get("data"))
        if op == "document.create_markdown":
            return self.os_manager.doc_create(t, doc_type="markdown", content=p.get("content", ""))
        if op == "document.create_pdf":
            return self.os_manager.doc_create(t, doc_type="pdf", title=p.get("title", "Untitled"), content=p.get("content", ""))
        if op == "document.compare":
            return self.os_manager.doc_compare(t, p.get("other_path", ""))
        if op == "document.summarize":
            return self.os_manager.doc_summarize(t, max_length=p.get("max_length"))
        if op == "document.edit":
            return self.os_manager.doc_edit(
                t,
                p.get("find_text", ""),
                p.get("replace_text", ""),
                output=p.get("output") or p.get("output_path"),
            )
        if op == "document.transform":
            return self.os_manager.doc_transform(t, p.get("output_path", ""), p.get("output_format", "txt"))
        if op == "document.verify":
            return self.os_manager.doc_verify(t, expected_content=p.get("expected_content"), expected_format=p.get("expected_format"))

        # -----------------------------------------------------
        # LEVEL 3.14+ — SPREADSHEET INTELLIGENCE
        # -----------------------------------------------------

        if op == "spreadsheet.inspect":
            return self.os_manager.sheet_inspect(t)
        if op == "spreadsheet.read":
            return self.os_manager.sheet_read(t, sheet_name=p.get("sheet_name"))
        if op == "spreadsheet.sort":
            return self.os_manager.sheet_sort(
                p.get("source") or t,
                p.get("column", ""),
                descending=bool(p.get("descending", True)),
                output=p.get("output"),
            )
        if op == "spreadsheet.filter":
            return self.os_manager.sheet_filter(t, p.get("sheet_name", ""), p.get("column", ""), p.get("condition", "equals"), p.get("value", ""))
        if op == "spreadsheet.calculate":
            return self.os_manager.sheet_calculate(t, p.get("sheet_name", ""), p.get("formula_column", ""), p.get("formula_template", ""))
        if op == "spreadsheet.rank":
            return self.os_manager.sheet_rank(t, p.get("sheet_name", ""), p.get("rank_column", ""), output=p.get("output"))
        if op == "spreadsheet.group_by":
            return self.os_manager.sheet_group_by(t, p.get("sheet_name", ""), p.get("column", ""), agg_column=p.get("agg_column"), operation=p.get("operation", "count"))
        if op == "spreadsheet.aggregate":
            return self.os_manager.sheet_aggregate(t, p.get("sheet_name", ""), p.get("columns", []), operation=p.get("operation", "sum"))
        if op == "spreadsheet.compare":
            return self.os_manager.sheet_compare(t, p.get("sheet1", ""), p.get("other_path", ""), p.get("sheet2", ""))
        if op == "spreadsheet.add_column":
            return self.os_manager.sheet_add_column(t, p.get("sheet_name"), p.get("column_name", p.get("column", "")), p.get("values", []), output=p.get("output"))
        if op == "spreadsheet.update_cell":
            return self.os_manager.sheet_update_cell(t, p.get("sheet_name"), int(p.get("row", 0)), p.get("column", ""), p.get("value"), output=p.get("output"))
        if op == "spreadsheet.create_from_dicts":
            return self.os_manager.sheet_create_from_dicts(t, p.get("data", []), sheet_name=p.get("sheet_name", "Sheet1"))
        if op == "data.inspect":
            return self.os_manager.data_inspect(t)
        if op == "data.transform":
            return self.os_manager.data_transform(
                t,
                operation=p.get("operation", "filter"),
                output=p.get("output"),
                conditions=p.get("conditions", []),
                field=p.get("field", p.get("column", "")),
                ascending=bool(p.get("ascending", True)),
                group_by=p.get("group_by", []),
                aggregations=p.get("aggregations", []),
            )

        raise ValueError("Unsupported operation reached dispatch: " + str(op))

    # =========================================================
    # RESULT NORMALIZATION
    # =========================================================

    def _normalize_result(
        self,
        plan: ActionPlan,
        raw_result: Any,
    ) -> ActionResult:

        if isinstance(
            raw_result,
            ActionResult,
        ):
            return self._attach_plan_metadata(
                plan,
                raw_result,
            )

        if not isinstance(
            raw_result,
            dict,
        ):
            return ActionResult.failure_result(
                operation=plan.operation,
                target=plan.target,
                application=plan.application,
                message=(
                    "Genesis received an invalid result "
                    "from the operating-system layer."
                ),
                status="invalid_execution_result",
                error=(
                    "OSManager returned a non-dictionary "
                    "execution result."
                ),
                executed=True,
                verified=False,
                plan=plan.to_dict(),
                metadata={
                    "executor_version": self.VERSION,
                    "execution_contract": (
                        self.EXECUTION_CONTRACT
                    ),
                    "normalization_stage": "type",
                    "raw_result_type": (
                        type(raw_result).__name__
                    ),
                },
            )

        raw_success = bool(
            raw_result.get(
                "success",
                False,
            )
        )
        raw_error = raw_result.get("error")
        raw_status = raw_result.get("status")
        failure_statuses = {
            "confirmation_required",
            "error",
            "execution_failed",
            "failed",
            "invalid_execution_result",
            "invalid_plan",
            "missing_target",
            "requires_confirmation",
            "safety_blocked",
            "unresolved_target",
            "verification_failed",
        }
        success = bool(
            raw_success
            and not raw_error
            and not (
                isinstance(raw_status, str)
                and raw_status.strip().lower() in failure_statuses
            )
        )

        message = raw_result.get(
            "message",
            "",
        )

        if not isinstance(
            message,
            str,
        ):
            message = ""

        executed = self._derive_executed(
            raw_result
        )

        verified = bool(
            success
            and self._derive_verified(
                raw_result
            )
        )

        already_running = bool(
            success
            and raw_result.get(
                "already_running",
                False,
            )
        )

        already_closed = bool(
            success
            and raw_result.get(
                "already_closed",
                False,
            )
        )

        already_desired = bool(
            verified
            and (
                already_running
                or already_closed
            )
        )

        status = self._derive_status(
            raw_result,
            success=success,
            executed=executed,
            verified=verified,
        )

        execution = (
            self._extract_execution_evidence(
                raw_result
            )
        )

        verification = (
            self._extract_verification_evidence(
                raw_result
            )
        )

        if raw_error:
            success = False
            verified = False
            already_desired = False
            status = "execution_failed"
        elif not raw_success:
            verified = False
            already_desired = False
            if isinstance(raw_status, str) and raw_status.strip():
                status = raw_status.strip()
        elif executed and not verified:
            status = "verification_failed"
        elif status == "failed" and isinstance(raw_status, str) and raw_status.strip():
            status = raw_status.strip()

        normalized = ActionResult(
            success=success,
            operation=plan.operation,
            target=plan.target,
            application=(
                raw_result.get(
                    "application"
                )
                or plan.application
            ),
            status=status,
            message=message,
            executed=executed,
            verified=verified,
            already_in_desired_state=(
                already_desired
            ),
            retry_count=int(
                raw_result.get(
                    "retry_count",
                    0,
                )
                or 0
            ),
            error=raw_error,
            execution=execution,
            verification=verification,
            plan=plan.to_dict(),
            metadata={
                "executor_version": self.VERSION,
                "execution_contract": (
                    self.EXECUTION_CONTRACT
                ),
                "raw_operation": (
                    raw_result.get(
                        "operation"
                    )
                ),
                "application_type": (
                    raw_result.get(
                        "application_type"
                    )
                ),
                "raw_status": raw_status,
            },
        )
        normalized.metadata["trustworthy_success"] = (
            normalized.trustworthy_success
        )
        return normalized

    # =========================================================
    # EXECUTION STATE
    # =========================================================

    @staticmethod
    def _derive_executed(
        result: Dict[str, Any],
    ) -> bool:

        explicit = result.get(
            "executed"
        )

        if isinstance(
            explicit,
            bool,
        ):
            return explicit

        if result.get(
            "already_running"
        ):
            return False

        if result.get(
            "already_closed"
        ):
            return False

        execution_keys = (
            "resolved_executable",
            "resolved_uri",
            "return_code",
        )

        if any(
            key in result
            for key in execution_keys
        ):
            return True

        return bool(
            result.get(
                "execution_attempted",
                False,
            )
        )

    # =========================================================
    # VERIFICATION STATE
    # =========================================================

    @staticmethod
    def _derive_verified(
        result: Dict[str, Any],
    ) -> bool:

        explicit = result.get(
            "verified"
        )

        if isinstance(
            explicit,
            bool,
        ):
            return explicit

        if result.get("already_running"):
            return bool(result.get("verified", False))
        if result.get("already_closed"):
            return bool(result.get("verified", False))

        return False

    # =========================================================
    # EXECUTION EVIDENCE
    # =========================================================

    @staticmethod
    def _extract_execution_evidence(
        result: Dict[str, Any],
    ) -> Dict[str, Any]:

        keys = (
            "operation",
            "executed",
            "execution_attempted",
            "resolved_executable",
            "resolved_uri",
            "application_type",
            "opened_file",
            "file_argument",
            "return_code",
            "already_running",
            "already_closed",
        )

        return {
            key: result.get(key)
            for key in keys
            if key in result
        }

    # =========================================================
    # VERIFICATION EVIDENCE
    # =========================================================

    @staticmethod
    def _extract_verification_evidence(
        result: Dict[str, Any],
    ) -> Dict[str, Any]:

        keys = (
            "verified",
            "verification_type",
            "verification_method",
            "verification_reason",
            "verification_attempts",
            "post_state_matches",
            "content_match",
            "content_verification",
            "all_passed",
            "output_path",
            "summary_verified",
            "similarity",
            "schema",
            "content_preview",
            "content_length",
            "content_truncated",
            "empty",
            "running",
            "muted",
            "volume_percent",
            "brightness_percent",
            "battery_percent",
            "battery_present",
            "plugged_in",
            "battery_status",
            "cpu_percent",
            "memory_percent",
            "memory_used_gb",
            "memory_total_gb",
            "uptime_hours",
            "uptime_minutes",
            "per_display",
            "local_time",
            "local_date",
            "report",
            "drives",
            "platform",
            "release",
            "processes",
            "pids",
            "available",
            "process_found",
            "opened_file",
            "file_argument",
            "url_readback",
            "requested_url",
            "search_verified",
            "tab_state_verified",
            "selection_verified",
            "click_postcondition_verified",
            "state_check_passed",
            "upload_readback_verified",
            "scroll_position_changed",
            "file_matches",
            "output_matches",
            "source_removed",
            "destination_exists",
            "file_exists",
            "folder_exists",
            "image_decoded",
            "old_path_exists",
            "item_count",
            "row_count",
            "count",
            "query",
            "text",
            "title",
            "url",
            "actual_url",
            "actual_title",
            "actual_value",
            "selected_value",
            "input_value",
            "rows",
            "items",
            "matches",
            "tabs",
            "scroll_after",
            "records",
            "result",
            "result_count",
            "actual",
        )

        evidence = {
            key: result.get(key)
            for key in keys
            if key in result
        }
        for container_name in ("verification", "metadata", "gui_metadata"):
            provider_verification = result.get(container_name)
            if isinstance(provider_verification, dict):
                evidence.update({
                    key: value
                    for key, value in provider_verification.items()
                    if key != "verified"
                })
        content_verification = result.get("content_verification")
        if isinstance(content_verification, dict):
            for key in ("content_match", "content_read", "content_method", "content_observed", "content_length"):
                if key in content_verification:
                    evidence[key] = content_verification[key]
        provider_data = result.get("data")
        if isinstance(provider_data, dict):
            for key in (
                "content_match",
                "content_verification",
                "output_path",
                "output_matches",
                "summary_verified",
                "similarity",
                "schema",
                "matches",
                "rows",
                "headers",
                "values",
                "records",
                "actual_value",
                "input_value",
                "observed_text",
                "read_method",
                "post_state_matches",
                "url_readback",
                "requested_url",
                "selection_verified",
                "click_postcondition_verified",
                "state_check_passed",
                "tab_state_verified",
                "scroll_position_changed",
            ):
                if key in provider_data:
                    evidence[key] = provider_data[key]
            if "observed_text" in provider_data and "content_preview" not in evidence:
                evidence["content_preview"] = str(provider_data["observed_text"])[:2000]
                evidence["content_length"] = len(str(provider_data["observed_text"]))

        # Read-path content MUST reach the caller (model/agent):
        # os_manager read ops carry the real provider payload in
        # ``data`` (e.g. document.read ``{"text": ...}``). Surface a
        # capped preview here so verified reads are also usable
        # reads. Cap prevents unbounded growth; full text was
        # observed from the real file, never synthesized.
        if "content_preview" not in evidence:
            data = result.get("data")
            text = None
            if isinstance(data, dict):
                text = data.get("text")
            if isinstance(text, str) and text:
                evidence["content_preview"] = text[:2000]
                evidence["content_length"] = len(text)
                evidence["content_truncated"] = len(text) > 2000

        return evidence

    # =========================================================
    # STATUS
    # =========================================================

    @staticmethod
    def _derive_status(
        result: Dict[str, Any],
        *,
        success: bool,
        executed: bool,
        verified: bool,
    ) -> str:

        if success and verified and result.get("already_running"):
            return "already_running"

        if success and verified and result.get("already_closed"):
            return "already_closed"

        if result.get(
            "error"
        ):
            return "execution_failed"

        if success and verified:
            return "verified"

        if executed and not verified:
            return "verification_failed"

        if success:
            return "success"

        return "failed"

    # =========================================================
    # PLAN METADATA
    # =========================================================

    def _attach_plan_metadata(
        self,
        plan: ActionPlan,
        result: ActionResult,
    ) -> ActionResult:

        if not result.plan:
            result.plan = plan.to_dict()

        result.metadata.setdefault(
            "executor_version",
            self.VERSION,
        )

        result.metadata.setdefault(
            "execution_contract",
            self.EXECUTION_CONTRACT,
        )

        return result
