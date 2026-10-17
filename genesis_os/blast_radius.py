"""Genesis OS — blast-radius classification and dynamic evaluation.

This module holds the *decision* half of the blast-radius model. The
*declaration* half lives on each capability's own
:class:`~genesis_os.capabilities.CapabilityDescriptor` as a static
``blast_radius`` default, next to ``preconditions`` and
``supported_inputs``.

Why the split: the static tier is declarative data and belongs on the
descriptor, where it is reviewed and versioned with the capability. A
dynamic evaluator is executable behaviour that depends on the arguments
of one specific call (does this destination already exist? does this
button say "delete"?), which cannot be expressed as frozen descriptor
data. Keeping the evaluator in a registry rather than as a second
external list of capability ids is deliberate — it is keyed by
capability id but it can only ever *raise* the tier of a capability
that already declares its own baseline.

THE NO-DOWNGRADE INVARIANT
--------------------------
An evaluator may escalate a capability's tier but never lower it. The
static descriptor value is a floor, not a suggestion.

The enforcement point is resolution time, not registration time, and
that is forced rather than chosen: an evaluator's return value is only
known when it is called, so a downgrade cannot be rejected when the
evaluator is registered. ``resolve_blast_radius`` therefore discards a
less-restrictive evaluator result and keeps the static floor.

Every real use is an escalation, so nothing legitimate is lost:

* ``browser.click`` declares ``REVERSIBLE_LOCAL`` (clicking a link is
  harmless) and escalates to ``IRREVERSIBLE_OR_OUTWARD`` when the
  target element's accessible text carries a high-risk signal such as
  "delete", "buy" or "send", or when the element exposes no accessible
  text at all and is therefore unassessable.
* ``file.move`` / ``file.rename`` declare ``REVERSIBLE_LOCAL`` (a move
  can be moved back) and escalate when the destination already exists,
  because overwriting it destroys the previous contents irreversibly.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .capabilities import BlastRadius

__all__ = [
    "BlastRadius",
    "DynamicEvaluator",
    "register_dynamic_evaluator",
    "dynamic_evaluator_for",
    "has_dynamic_evaluator",
    "resolve_blast_radius",
    "resolve_operation_blast_radius",
    "register_unsaved_changes_detector",
    "coverage_gaps",
    "record_coverage_gap",
    "HIGH_RISK_CLICK_SIGNALS",
    "click_risk_signal",
    "browser_click_escalation",
    "overwrite_destination_escalation",
    "application_close_escalation",
]


# Most restrictive first. resolve_blast_radius takes the earliest tier
# present, so ordering here defines restrictiveness.
TIER_ORDER = (
    BlastRadius.IRREVERSIBLE_OR_OUTWARD,
    BlastRadius.REVERSIBLE_LOCAL,
)


def restrictiveness(tier: BlastRadius) -> int:
    """Lower index == more restrictive."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        # An unknown tier must never be treated as permissive.
        return 0


def more_restrictive(
    left: BlastRadius, right: BlastRadius
) -> BlastRadius:
    """The more conservative of two tiers. Never returns the laxer one."""
    if restrictiveness(left) <= restrictiveness(right):
        return left
    return right


# ---------------------------------------------------------------------
# EVALUATOR REGISTRY
# ---------------------------------------------------------------------

# An evaluator receives the call arguments and, optionally, the
# execution-time security context (for browser.click this carries the
# element_text / alt_text / aria_label that only the executor can
# extract). context is keyword-optional so a single-argument evaluator
# remains valid.
DynamicEvaluator = Callable[..., Optional[BlastRadius]]

_lock = threading.RLock()
_evaluators: Dict[str, DynamicEvaluator] = {}


def register_dynamic_evaluator(
    capability_id: str,
    evaluator: DynamicEvaluator,
    *,
    replace: bool = False,
) -> None:
    """Register a per-call tier evaluator for ``capability_id``.

    The evaluator returns a :class:`BlastRadius` to escalate to, or
    ``None`` to decline and leave the static default in force.
    """
    if not isinstance(capability_id, str) or not capability_id.strip():
        raise ValueError("capability_id must be a non-empty string")
    if not callable(evaluator):
        raise TypeError("evaluator must be callable")
    capability_id = capability_id.strip()
    with _lock:
        existing = _evaluators.get(capability_id)
        if existing is not None and existing is not evaluator and not replace:
            raise ValueError(
                f"an evaluator is already registered for "
                f"{capability_id!r}; pass replace=True to override"
            )
        _evaluators[capability_id] = evaluator


def dynamic_evaluator_for(
    capability_id: str,
) -> Optional[DynamicEvaluator]:
    with _lock:
        return _evaluators.get(capability_id)


def has_dynamic_evaluator(capability_id: str) -> bool:
    return dynamic_evaluator_for(capability_id) is not None


def resolve_blast_radius(
    capability_id: str,
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    static_default: Optional[BlastRadius] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> BlastRadius:
    """Resolve the effective tier for one call.

    ``static_default`` is the capability's declared baseline. When it is
    omitted the descriptor's value is used. The registered evaluator,
    if any, may only make the result MORE restrictive.

    A capability with no evaluator resolves to its static default
    exactly — adding this mechanism must not change any capability that
    did not opt into it.
    """
    if static_default is None:
        static_default = _static_default_for(capability_id)

    tier = static_default
    evaluator = dynamic_evaluator_for(capability_id)
    if evaluator is not None:
        try:
            verdict = evaluator(dict(arguments or {}), context)
        except Exception:
            # An evaluator that blows up must not silently downgrade the
            # capability. Fall back to the declared floor.
            verdict = None
        if isinstance(verdict, BlastRadius):
            tier = more_restrictive(static_default, verdict)

    # ---- workspace boundary: universal, tier-independent ----------
    # Applied AFTER the capability's own evaluator so it can only ever
    # escalate. A Tier 2 capability targeting something outside the
    # configured workspace becomes Tier 1 FOR THAT CALL and must
    # present a genuine AuthorizationGrant.
    #
    # Deliberately NOT an evaluator: an evaluator is per-capability and
    # can be absent. This must apply to EVERY capability, including ones
    # nobody registered an evaluator for, so it lives in the shared
    # resolver. It is applied here rather than in the no-evaluator
    # early-return path precisely because that path is the common case
    # -- an earlier version returned the static default before reaching
    # this check, so the boundary never fired for any capability
    # without an evaluator.
    if tier is BlastRadius.REVERSIBLE_LOCAL:
        try:
            from .workspace_boundary import arguments_escape_workspace

            if arguments_escape_workspace(arguments, capability_id=capability_id):
                tier = BlastRadius.IRREVERSIBLE_OR_OUTWARD
        except Exception:
            # Fail closed on a broken boundary check rather than
            # silently permitting out-of-bounds writes.
            tier = BlastRadius.IRREVERSIBLE_OR_OUTWARD

    return tier


def _static_default_for(capability_id: str) -> BlastRadius:
    try:
        from .capability_registry import CapabilityRegistry

        descriptor = CapabilityRegistry.get(capability_id)
    except Exception:
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD
    return getattr(
        descriptor, "blast_radius", BlastRadius.IRREVERSIBLE_OR_OUTWARD
    )


# ---------------------------------------------------------------------
# GENERAL FALLBACK — the durable fix for uncovered dangerous operations
# ---------------------------------------------------------------------
#
# MEASURED 2026-10-07: `system.shutdown` and `system.restart` appeared
# in CapabilityRegistry._dangerous_operations but had NO capability
# descriptor, so the blast-radius model could not see them at all. A
# dangerous operation that nobody registered is not merely
# unclassified — it is invisible, and an invisible operation cannot be
# gated by anything that reads tiers.
#
# This closes that class of bug rather than the instance. Any operation
# with no registered descriptor resolves to Tier 1 and is recorded in
# the coverage-gap log, so the next one is visible immediately instead
# of being discovered by inspection months later.
#
# Deny-by-default is deliberate and matches the descriptor default: an
# operation Genesis cannot classify cannot be shown to be reversible.

_coverage_gaps: "list[dict[str, Any]]" = []


def record_coverage_gap(entry: Dict[str, Any]) -> None:
    """Append a coverage gap, de-duplicated on operation."""
    key = entry.get("operation")
    for existing in _coverage_gaps:
        if existing.get("operation") == key:
            return
    _coverage_gaps.append(entry)


def coverage_gaps() -> "list[dict[str, Any]]":
    """Operations that reached the tier resolver without a descriptor."""
    return [dict(gap) for gap in _coverage_gaps]


def identify_capability(
    operation: str,
    capability_id: Optional[str] = None,
) -> Optional[str]:
    """Return the registered capability_id for these identifiers.

    Returns ``None`` when nothing matched, which is the signal the
    executor uses to decide whether the legacy risk-profile gate must
    stand in (blast radius could not classify it, so deny-by-default
    plus the old table applies).

    Matching order — capability_id field, then the ``operation`` string
    against the capability_id field (ActionPlan.operation is frequently
    a capability id), then the registered operation field.
    """
    try:
        from .capability_registry import CapabilityRegistry

        all_caps = CapabilityRegistry.all()
    except Exception:
        return None
    if capability_id:
        for candidate in all_caps:
            if candidate.capability_id == capability_id:
                return candidate.capability_id
    if operation:
        for candidate in all_caps:
            if candidate.capability_id == operation:
                return candidate.capability_id
        for candidate in all_caps:
            if candidate.operation == operation:
                return candidate.capability_id
    return None


def resolve_operation_blast_radius(
    operation: str,
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    context: Optional[Mapping[str, Any]] = None,
    capability_id: Optional[str] = None,
) -> BlastRadius:
    """Resolve a tier from an OPERATION (or a capability id).

    Matching accepts EITHER identifier, because they disagree in the
    wild: ``ActionPlan.operation`` for a browser capability is the full
    capability id ("browser.wait") while the registry stores the bare
    verb ("wait") in ``operation``. Matching on only one of the two
    produced deny-by-default gating of legitimate Tier 2 capabilities.

    ``capability_id`` is tried first when supplied, since it is
    unambiguous; ``operation`` is the fallback for direct executor
    callers that never set it.

    This is the entry point an enforcement layer should call. It is
    deliberately more conservative than
    ``resolve_blast_radius(capability_id, ...)``:

    * a registered capability resolves through its static tier and its
      dynamic evaluator, exactly as before;
    * an identifier with no registered descriptor resolves to Tier 1 and
      is recorded as a coverage gap.
    """
    capability_id = capability_id or None
    descriptor = None
    resolved_capability = None
    try:
        from .capability_registry import CapabilityRegistry

        all_caps = CapabilityRegistry.all()
        # Try the explicit capability_id against the capability_id field.
        if capability_id:
            for candidate in all_caps:
                if candidate.capability_id == capability_id:
                    descriptor = candidate
                    resolved_capability = candidate.capability_id
                    break
        # Then try the `operation` string against the capability_id
        # field. ActionPlan.operation is NOT always the registered
        # operation: direct executor callers routinely put the
        # CAPABILITY ID there ("package.search", not "search"). Skipping
        # this match is what made read-only Tier 2 capabilities
        # (package.search, cleanup.recycle_bin_query, web.research)
        # deny-by-default to Tier 1.
        if descriptor is None and operation:
            for candidate in all_caps:
                if candidate.capability_id == operation:
                    descriptor = candidate
                    resolved_capability = candidate.capability_id
                    break
        # Then the registered operation field.
        if descriptor is None and operation:
            for candidate in all_caps:
                if candidate.operation == operation:
                    descriptor = candidate
                    resolved_capability = candidate.capability_id
                    break
    except Exception:
        descriptor = None

    if descriptor is None:
        declared_dangerous = False
        try:
            from .capability_registry import CapabilityRegistry

            declared_dangerous = (
                operation in CapabilityRegistry._dangerous_operations
            )
        except Exception:
            declared_dangerous = False
        record_coverage_gap({
            "operation": operation,
            "declared_dangerous": declared_dangerous,
            "resolved_tier": BlastRadius.IRREVERSIBLE_OR_OUTWARD.value,
            "detail": (
                "No registered capability descriptor. "
                + (
                    "Declared in _dangerous_operations, so this is a "
                    "known-dangerous operation with no descriptor."
                    if declared_dangerous
                    else "Not declared dangerous either, so nothing "
                    "describes its blast radius at all."
                )
            ),
        })
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD

    return resolve_blast_radius(
        resolved_capability,
        arguments,
        static_default=getattr(
            descriptor,
            "blast_radius",
            BlastRadius.IRREVERSIBLE_OR_OUTWARD,
        ),
        context=context,
    )



# ---------------------------------------------------------------------
# EVALUATOR 1 — browser.click
# ---------------------------------------------------------------------
#
# Migrated from the standalone heuristic that previously lived inline in
# security_model.assess_operation_risk. The signal list and the
# detection function now have exactly one definition, here, and
# security_model imports them, so there is no second parallel system.

HIGH_RISK_CLICK_SIGNALS = frozenset(
    {
        "delete", "remove", "destroy", "erase",
        "buy", "purchase", "order", "checkout", "pay",
        "send", "submit", "confirm", "approve",
        "unsubscribe", "cancel subscription",
        "close account", "deactivate", "disable",
        "transfer", "wire", "invest",
    }
)


def click_risk_signal(accessible_text: str) -> Optional[str]:
    """Return the first high-risk signal found in ``accessible_text``."""
    if not isinstance(accessible_text, str):
        return None
    lowered = accessible_text.lower()
    for signal in HIGH_RISK_CLICK_SIGNALS:
        if signal in lowered:
            return signal
    return None


def _accessible_click_text(context: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(context, Mapping):
        return ""
    parts = []
    for key in ("element_text", "alt_text", "aria_label"):
        value = context.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return " ".join(parts)


def browser_click_escalation(
    arguments: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> Optional[BlastRadius]:
    """Escalate ``browser.click`` when the target looks irreversible.

    Two escalation conditions, both inherited from the heuristic this
    replaces:

    1. The element's accessible text carries a high-risk signal
       ("delete", "buy", "send", ...). Clicking it very likely commits
       something irreversible or outward-facing.
    2. The element exposes no accessible text at all and is marked
       unassessable. Per the project's "real state over assumptions"
       principle, an element Genesis cannot read is treated as unknown
       risk rather than assumed harmless.

    Returns ``None`` (static default stands) for an ordinary link or
    button with readable text.
    """
    text = _accessible_click_text(context)
    if click_risk_signal(text):
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD
    if isinstance(context, Mapping) and context.get("_no_element_text"):
        if not text:
            return BlastRadius.IRREVERSIBLE_OR_OUTWARD
    return None


# ---------------------------------------------------------------------
# EVALUATOR 2 — file.move / file.rename
# ---------------------------------------------------------------------

_DESTINATION_ARG_KEYS = (
    "destination", "output", "output_path", "save_path", "target_path",
)


def overwrite_destination_escalation(
    arguments: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
    *,
    operation: Optional[str] = None,
) -> Optional[BlastRadius]:
    """Escalate when a write would DESTROY data that already exists.

    Writing to a free destination is reversible: delete it. Writing
    onto an existing file destroys whatever was there, and nothing can
    bring it back. That is the difference the static default cannot
    express, so it is checked per call.

    Per-operation destination resolution (2026-10-15, Item 3B-3a)
    -----------------------------------------------------------
    This evaluator used to read only ``_DESTINATION_ARG_KEYS``
    (``destination``/``output``/``output_path``/``save_path``/
    ``target_path``). Two consequences:

    1. ``file.rename`` and ``folder.rename`` pass ``new_name``, which
       was never in that tuple, so the evaluator read NO destination
       and always returned ``None``. The rename escalations were
       registered but unreachable on the real executor path.
    2. ``file.copy``, ``file.create`` and ``document.create_docx`` had
       no evaluator at all, so overwriting an existing file through
       them was ungated.

    Which argument names the destination depends on the operation, and
    ``arguments`` alone does not say which operation this is. So this
    function is REGISTERED PER OPERATION with its id bound in by
    ``_overwrite_escalation_for``. ``operation`` is supplied by that
    binding; when called directly without it, every known destination
    key is tried so it stays correct standalone.

    Returns ``None`` when there is no destination, or the destination
    does not exist (a free target stays Tier 2).
    """
    if not isinstance(arguments, Mapping):
        return None

    destination = _resolve_overwrite_destination(operation, arguments)
    if destination is None:
        return None

    try:
        return (
            BlastRadius.IRREVERSIBLE_OR_OUTWARD
            if os.path.exists(destination)
            else None
        )
    except OSError:
        # Cannot determine; assume the destructive case.
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD


# Per-operation destination keys, matching what ActionExecutor._dispatch
# actually forwards to the OS manager. ``new_name`` is a BARE name, not
# a full path, so for the rename operations it must be joined onto the
# source's parent directory before existence can be checked.
_OVERWRITE_DESTINATION_KEYS: Dict[str, Tuple[str, ...]] = {
    "file.move":        ("destination",),
    "folder.move":      ("destination",),
    "file.rename":      ("new_name",),
    "folder.rename":    ("new_name",),
    "file.copy":        ("destination",),
    "file.create":      ("path",),
    "document.create_docx": ("path", "output_path", "destination"),
}

# Operations whose destination arrives as a BARE ``new_name``, which must
# be resolved against the source's parent rather than the process CWD.
_RENAME_OPERATIONS = frozenset({"file.rename", "folder.rename"})


def _resolve_overwrite_destination(
    operation: Optional[str],
    arguments: Mapping[str, Any],
) -> Optional[str]:
    """The path this call would write onto, or None.

    The operation's PRIMARY destination key is tried first, then the
    generic destination keys (``destination``/``output``/``output_path``/
    ``save_path``/``target_path``). The fallback matters: callers may use
    any of them for any operation, and
    ``test_alternate_destination_argument_names_are_honoured`` pins that
    the alternate names are inspected.
    """
    keys = _OVERWRITE_DESTINATION_KEYS.get(operation or "")
    # An ABSOLUTE path among the generic destination keys is an explicit
    # full destination and always wins over a bare `new_name`, which only
    # means anything relative to the source.
    generic_absolute = None
    for key in _DESTINATION_ARG_KEYS:
        candidate = arguments.get(key)
        if (isinstance(candidate, (str, os.PathLike)) and str(candidate).strip()
                and os.path.isabs(os.fspath(candidate))):
            generic_absolute = os.fspath(candidate)
            break

    value = None
    if generic_absolute is not None:
        value = generic_absolute
    else:
        candidate_keys = (tuple(keys) + tuple(_DESTINATION_ARG_KEYS)
                          if keys else tuple(_DESTINATION_ARG_KEYS))
        for key in candidate_keys:
            candidate = arguments.get(key)
            if (isinstance(candidate, (str, os.PathLike))
                    and str(candidate).strip()):
                value = os.fspath(candidate)
                break
    if value is None:
        return None

    # `file.create` only destroys an existing file when the caller asked
    # to overwrite. Without the flag the manager refuses, so this call is
    # not destructive and must stay Tier 2.
    if operation == "file.create" and not bool(arguments.get("overwrite")):
        return None

    # A rename carrying a BARE new_name must be resolved beside the
    # source. A rename that supplied an absolute destination key is
    # already a full path and is used as-is.
    if operation in _RENAME_OPERATIONS and not os.path.isabs(value):
        source = arguments.get("source") or arguments.get("path")
        if isinstance(source, (str, os.PathLike)) and str(source).strip():
            try:
                parent = os.path.dirname(os.path.abspath(os.fspath(source)))
                if not parent:
                    return os.path.join(".", "__unresolvable__")
                return os.path.join(parent, value)
            except (OSError, ValueError, TypeError):
                # Cannot resolve the destination. Fail closed.
                return os.path.join(".", "__unresolvable__")
        # No source to anchor against; fail closed.
        return os.path.join(".", "__unresolvable__")

    return value


def _overwrite_escalation_for(operation: str) -> DynamicEvaluator:
    """Bind an operation id into the overwrite evaluator.

    ``DynamicEvaluator`` is ``Callable[..., Optional[BlastRadius]]`` and
    the resolver invokes ``evaluator(arguments, context)``; this wrapper
    supplies the id the arguments alone cannot express.
    """

    def _evaluate(
        arguments: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[BlastRadius]:
        return overwrite_destination_escalation(
            arguments, context, operation=operation
        )

    _evaluate.__name__ = f"overwrite_escalation[{operation}]"
    return _evaluate


# ---------------------------------------------------------------------
# EVALUATOR 3 — application.close (unsaved work)
# ---------------------------------------------------------------------
#
# Closing an application with unsaved work destroys that work. That is
# irreversible, so application.close must not be trusted to its static
# reversible_local default for this call.
#
# Before this evaluator, the escalation lived ONLY in
# AgentFrameworkAdapter._check_unsaved_changes_precondition — a
# separate mechanism. Two mechanisms both claiming authority over the
# same question is how they drift, and it meant blast_radius alone did
# not describe the risk: an enforcement layer reading only tiers would
# have let unsaved-work loss through silently.
#
# AUTHORITY: the evaluator is now the single decision point. The
# platform-specific detection (Windows user32 window enumeration) stays
# in the adapter, where it already lived, and is injected here as a
# detector. Adapter._check_unsaved_changes_precondition delegates to
# resolve_blast_radius, so the precondition gate and the tier can never
# disagree.
#
# A MISSING detector yields no escalation, so the precondition can never
# prompt on every routine close. That distinction matters, so it is
# spelled out precisely, because the two cases are NOT the same:
#
#   * MISSING detector (detector is None) -> no escalation. The platform
#     genuinely cannot answer, e.g. application.close on a box with no
#     user32. Prompting on every close there would make the product
#     unusable, so it stays quiet.
#
#   * REGISTERED detector that RAISES -> escalation, since Item 7B. A
#     check that was asked and failed is not a verdict of "nothing
#     unsaved", so it fails closed to IRREVERSIBLE_OR_OUTWARD.
#
# CORRECTION (Item 10B, S11). This comment used to justify the
# no-escalation case by saying "false negatives are caught by the
# executor's safety policy further down". THAT WAS FALSE.
# ExecutionSafety.check() is a deny-list plus a capability lookup; it
# never inspects windows, documents or unsaved state. There is no such
# downstream safety net. The justification for the missing-detector case
# stands on its own -- do not prompt on an unsupported platform -- but it
# is a product trade-off, not a backstop.

_unsaved_changes_detectors: Dict[str, Callable[..., Any]] = {}


def register_unsaved_changes_detector(
    capability_id: str,
    detector: Callable[..., Any],
) -> None:
    """Register the platform-specific unsaved-work detector.

    The detector is called as ``detector(arguments)`` and must return
    ``(active: bool, reason: str)``.
    """
    if not callable(detector):
        raise TypeError("detector must be callable")
    with _lock:
        _unsaved_changes_detectors[capability_id.strip()] = detector


def application_close_escalation(
    arguments: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> Optional[BlastRadius]:
    """Escalate ``application.close`` when unsaved work is present."""
    detector = _unsaved_changes_detectors.get("application.close")
    if detector is None:
        return None
    try:
        active, _reason = detector(dict(arguments or {}))
    except Exception:
        # Fail closed (Directive 7B).
        #
        # A detector that is REGISTERED and then raises is an error, not
        # a verdict. The previous `return None` was indistinguishable
        # from "checked, found nothing", so a crashed detector silently
        # downgraded application.close to its static tier and let a
        # close with possible unsaved work through ungated.
        #
        # This cannot cause the "prompt on every routine close"
        # regression that the missing-detector case guards against.
        # Both unsupported-platform paths RETURN a verdict rather than
        # raising: the ctypes import failure returns
        # (False, "user32 unavailable on this platform"), and the
        # EnumWindows failure path returns (False, reason). Neither
        # reaches this handler. Only a genuinely unexpected error does.
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD
    if active:
        return BlastRadius.IRREVERSIBLE_OR_OUTWARD
    return None


def _register_builtin_evaluators() -> None:
    register_dynamic_evaluator(
        "browser.click", browser_click_escalation, replace=True
    )
    register_dynamic_evaluator(
        "application.close", application_close_escalation, replace=True
    )
    for capability_id in (
        # Already registered (2026-10-08). file.rename/folder.rename are
        # included here but were DEAD: the evaluator read only
        # destination-shaped keys and those ops pass a bare new_name.
        "file.move", "file.rename", "folder.move", "folder.rename",
        # Added 2026-10-15 (Item 3B-3a): mutators that can destroy an
        # existing file but had no evaluator, so overwriting through
        # them was ungated at the authority.
        "file.copy", "file.create", "document.create_docx",
    ):
        register_dynamic_evaluator(
            capability_id,
            _overwrite_escalation_for(capability_id),
            replace=True,
        )


_register_builtin_evaluators()
