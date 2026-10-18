"""
Genesis OS — Action Plan

LEVEL 3.3
---------

Mature execution intent contract.

Architecture:

    WorkflowDecisionEngine
            ↓
        ActionPlan
            ↓
      ActionExecutor
            ↓
        OSManager

ActionPlan represents WHAT Genesis intends to do.

It NEVER performs an operating-system action.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, ClassVar, Dict, FrozenSet, Iterable, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .capability_catalog import CAPABILITIES


KNOWN_DENIED_OPERATIONS = frozenset({
    "system.shutdown",
    "system.restart",
    "system.sleep",
    "filesystem.delete",
    "filesystem.move",
    "filesystem.rename",
    "shell.execute",
    "process.kill",
})


# Lazy-imported inside ``_validate_against_registry`` to
# avoid an import cycle with ``action_executor``. The
# canonical capability allow-list is ``CapabilityRegistry``
# (the same one the executor, planner, and decomposer
# consult); ``ActionExecutor.SUPPORTED_OPERATIONS`` is the
# legacy mirror kept in sync with it.


class ActionPlanValidationError(ValueError):
    """
    Raised when an ActionPlan violates the execution contract.
    """


def _is_authorization_grant(value: Any) -> bool:
    """Structural check used by ActionPlan.__init__.

    Imported lazily-by-name to keep this module free of a circular
    import at module load: authorization_grant imports approval_store,
    which does not import action_plan, but a lazy name check keeps the
    dependency one-directional regardless.
    """
    try:
        from .authorization_grant import AuthorizationGrant
    except Exception:
        return False
    return isinstance(value, AuthorizationGrant)


def attach_authorization(
    plan: "ActionPlan", grant: Any, arguments: Optional[Any] = None
) -> "ActionPlan":
    """Return a copy of ``plan`` carrying ``grant``.

    Why the ATTACH point is not restricted even though the grant is:
    ``AuthorizationGrant`` refuses direct construction and can only be
    minted by consuming a real, argument-hash-bound approval. There is
    therefore no way to obtain a grant to attach. Restricting who may
    call this function would add ceremony without adding safety — the
    unforgeable object is the grant, not the act of attaching it.

    Still validated here so a mistake fails loudly rather than
    attaching something inert and silently ungating a Tier 1 plan.
    """
    if not _is_authorization_grant(grant):
        raise TypeError(
            "attach_authorization requires an AuthorizationGrant; got "
            f"{type(grant).__name__}"
        )
    arguments = dict(arguments or {})
    return plan.model_copy(
        update={
            "authorization": grant,
            "authorization_arguments": arguments,
        }
    )


class ActionPlan(BaseModel):
    """
    Immutable description of an intended Genesis OS action.

    Responsibilities:

        - represent intent
        - preserve confidence
        - preserve target
        - preserve application identity
        - preserve parameters
        - provide deterministic validation

    It does NOT:

        - launch applications
        - close applications
        - inspect processes
        - execute commands
        - modify Windows

    This is a Pydantic ``BaseModel`` for Phase 1 of the
    UCCL roadmap. All field-level invariants (string type,
    non-empty operation, dict parameters, finite numeric
    confidence in [0, 1], conditional target requirement
    via the canonical ``TARGETLESS_OPERATIONS`` set) are
    expressed as Pydantic validators at construction time
    so malformed/unsafe states are rejected early.

    The capability allow-list check runs during construction.
    Explicitly denied legacy operations remain representable so
    the executor can return the authoritative safety decision;
    unknown operations are rejected immediately.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    # ---------------------------------------------------------
    # Dataclass interop shim
    # ---------------------------------------------------------
    #
    # Several call sites in the production execution pipeline
    # (``genesis.py``, ``workflow_binding.py``,
    # ``workflow_target_resolver.py``) historically rebuild
    # an ActionPlan with ``dataclasses.replace(plan, ...)``.
    # Pydantic ``BaseModel`` is NOT a dataclass, so
    # ``dataclasses.replace`` would raise
    # ``TypeError: replace() should be called on dataclass
    # instances``.
    #
    # Expose a minimal ``__dataclass_fields__`` view so
    # ``dataclasses.replace`` accepts the instance, reads
    # each field via ``getattr``, and constructs the new
    # plan via ``cls(**changes)`` (which routes through
    # our overridden ``__init__`` and the full Pydantic
    # validation pipeline). This preserves the public
    # call-site contract while keeping Phase 1 Pydantic
    # validation intact.
    _DATACLASS_FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "operation",
        "target",
        "application",
        "task",
        "confidence",
        "parameters",
        "reason",
        "source",
        "version",
    )

    # Populated lazily below at class creation time.
    __dataclass_fields__: dict = {}

    operation: str

    target: Optional[str] = None

    application: Optional[str] = None

    task: str = ""

    confidence: float = 1.0

    parameters: Dict[str, Any] = Field(
        default_factory=dict
    )

    reason: str = ""

    # =========================================================
    # AUTHORIZATION (trusted adapter -> executor channel)
    # =========================================================
    #
    # Replaces the old ``parameters["confirmed"]`` boolean. The
    # difference is structural, not conventional: ``parameters`` is
    # deserialized from model-controlled JSON, so anything in it is
    # model-reachable. This field is typed as AuthorizationGrant, and
    # Pydantic validates arbitrary types by isinstance -- so a dict,
    # string, or boolean arriving from any deserialization path is
    # REFUSED at construction. AuthorizationGrant in turn refuses
    # direct construction and can only be minted by consuming a real,
    # argument-hash-bound approval.
    #
    # Net effect: there is no JSON-shaped input that yields a grant.
    #
    # Excluded from serialization so a grant never leaks into a
    # serialized plan, log line, or model-visible payload.

    authorization: Optional[Any] = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    # The exact argument set the grant was minted against. Travels on
    # the same trusted channel and is meaningless without a valid grant
    # (the executor requires both, and re-derives the hash from it).
    authorization_arguments: Optional[Any] = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    # The registered capability this plan invokes, when the caller
    # knows it. The adapter always knows it; the bare `operation` alone
    # is NOT sufficient to identify a capability, because browser
    # capabilities register with the bare verb as their operation
    # ("click", not "browser.click"). Gating on the operation string
    # therefore deny-defaulted 31 legitimate Tier 2 browser
    # capabilities when it was tried.
    #
    # Trusted-adapter metadata, not model input: the adapter sets it
    # from its own routing decision. It is advisory for gating only in
    # combination with `operation` -- the resolver takes the MOST
    # RESTRICTIVE of the two, so a wrong or absent capability_id can
    # only ever make a plan MORE gated, never less.
    capability_id: Optional[str] = None

    source: str = "WorkflowDecisionEngine"

    version: str = "3.3.2"

    # =========================================================
    # SUPPORTED OPERATIONS
    # =========================================================
    #
    # Item 5C (2026-10-15): this used to be a hand-authored
    # `frozenset({...})` of 121 operation strings that was
    # IMMEDIATELY overwritten on the next line by
    # `APPLICATION_OPERATIONS = CAPABILITIES`. The literal could
    # therefore never be observed by anything -- not by
    # `validate()`, not by a caller importing the constant.
    #
    # INTENT DETERMINED FROM USAGE, and the literal was the wrong
    # half. Three call sites describe this attribute as a STRICT
    # application-only subset and then deliberately work around it
    # to reach the full set:
    #
    #   workflow_planner.py:12  _full_supported_operations()
    #   agents/compound_task_router.py:289  'we deliberately do NOT
    #       call action_plan.validate() here with the strict
    #       APPLICATION_OPERATIONS default'
    #   action_plan.py validate() docstring: 'the planner and the
    #       executor pass the full SUPPORTED_OPERATIONS set'
    #
    # So the FULL set is the real contract; the literal was stale
    # (it is missing 20 registered capabilities such as
    # document.create_txt, document.read_intel and
    # browser.get_page_state). Restoring it would have REJECTED
    # those 20 capabilities in the four `validate()` call sites
    # that pass no allow-list. The literal is therefore DELETED
    # rather than restored, and the alias becomes the single
    # definition -- one source of truth, no dead code.
    #
    # The attribute itself is kept, because it is a documented
    # public surface that external code and the workarounds above
    # reference by name.
    APPLICATION_OPERATIONS: ClassVar[FrozenSet[str]] = CAPABILITIES

    # =========================================================
    # OPERATIONS THAT RESOLVE THEIR TARGET AT RUNTIME
    # =========================================================
    #
    # These operations do not require a planning-time target.
    # They describe an interaction with whatever window /
    # element currently has focus at execution time:
    #
    #   *   gui.type_text / gui.paste_text
    #         — keystroke injection into the focused window
    #
    #   *   gui.focus_window / gui.inspect_window
    #         — when the window is identified by a runtime
    #           selector, not a concrete name
    #
    #   *   gui.click / gui.double_click / gui.select / gui.scroll
    #         — may be anchored to coordinates / focused
    #           element resolved by GUIController at runtime
    #
    #   *   gui.read_visible_text / gui.keyboard_action
    #         — operations on the currently focused window
    #
    #   *   browser.scroll
    #         — page-level scroll direction comes from
    #           parameters; ``ActionExecutor._dispatch``
    #           (action_executor.py) does not consume the
    #           target for this operation, and
    #           ``ObservationLoop._observe_browser_scroll``
    #           likewise only consults parameters.
    #
    # ActionPlanner accepts target=None for these ops. The
    # ActionExecutor and GUIController either dispatch on
    # the focused window (when target is None) or, when
    # target is set, dispatch gui.focus_window first and
    # then the typed/clicked operation.
    #
    # This is the canonical capability contract for
    # generalized GUI text input. Without it, the planner
    # rejects a perfectly executable compound objective
    # ("open notepad and write Hello from Genesis") because
    # the second clause has no planning-time window name.
    TARGETLESS_OPERATIONS: ClassVar[FrozenSet[str]] = frozenset({
        "gui.type_text", "gui.paste_text",
        "gui.focus_window", "gui.inspect_window",
        "gui.click", "gui.double_click",
        "gui.select", "gui.scroll",
        "gui.read_visible_text", "gui.keyboard_action",
        "browser.scroll", "browser.extract", "browser.get_title",
        "browser.get_url", "browser.switch_tab", "browser.open_tab",
        "browser.close_tab", "browser.get_tabs", "browser.select",
        "browser.verify", "browser.wait", "browser.find",
        "browser.get_page_state",
        "document.search", "document.verify", "document.summarize",
        "document.compare",
        "spreadsheet.sort", "spreadsheet.inspect", "spreadsheet.read",
        "spreadsheet.filter", "spreadsheet.calculate", "spreadsheet.rank",
        "spreadsheet.group_by", "spreadsheet.aggregate",
        "spreadsheet.compare",
        "file.search",
        "clipboard.copy", "clipboard.paste",
        "notes.create", "notes.list",
        "media.play_pause", "media.next", "media.previous", "media.stop",
        "volume.up", "volume.down", "volume.mute_toggle",
        "volume.set", "volume.get",
        "display.brightness_set", "display.brightness_get",
        "hardware.battery", "hardware.stats", "hardware.storage",
        "system.status",
        "network.list_wifi",
        "application.list",
        "process.list",
        "window.minimize_all", "window.restore", "window.show_desktop",
        "cleanup.recycle_bin_query",
        "workstation.lock",
    })

    # =========================================================
    # FIELD-LEVEL PYDANTIC VALIDATORS
    # =========================================================

    @field_validator("operation")
    @classmethod
    def _operation_must_be_non_empty_string(
        cls,
        value: Any,
    ) -> str:
        """
        ``operation`` must be a non-empty string.

        Known denied operations are accepted so the executor
        can classify them at the safety boundary. Unknown
        operations are rejected during construction.
        """

        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan operation must be a string."
            )

        stripped = value.strip()

        if not stripped:
            raise ActionPlanValidationError(
                "ActionPlan operation cannot be empty."
            )
        if (
            stripped not in CAPABILITIES
            and stripped not in KNOWN_DENIED_OPERATIONS
        ):
            raise ActionPlanValidationError(
                f"Unknown Genesis capability: {stripped}."
            )

        return stripped

    @field_validator("target")
    @classmethod
    def _target_when_present_must_be_non_empty_string(
        cls,
        value: Any,
    ) -> Optional[str]:
        """
        When ``target`` is supplied, it must be a
        non-empty string. Whether target is *required*
        at all is decided by ``TARGETLESS_OPERATIONS``;
        see :meth:`_conditional_target_requirement`.
        """

        if value is None:
            return None

        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan target must be a string."
            )

        if not value.strip():
            raise ActionPlanValidationError(
                "ActionPlan target cannot be empty."
            )

        return value

    @field_validator("application")
    @classmethod
    def _application_when_present_must_be_non_empty_string(
        cls,
        value: Any,
    ) -> Optional[str]:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan application must "
                "be a string when provided."
            )

        if not value.strip():
            raise ActionPlanValidationError(
                "ActionPlan application cannot "
                "be an empty string."
            )

        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_must_be_finite_unit_float(
        cls,
        value: Any,
    ) -> float:
        if isinstance(value, bool) or not isinstance(
            value,
            (int, float),
        ):
            raise ActionPlanValidationError(
                "ActionPlan confidence must be numeric."
            )

        confidence = float(value)

        if not isfinite(confidence):
            raise ActionPlanValidationError(
                "ActionPlan confidence must be finite."
            )

        if not 0.0 <= confidence <= 1.0:
            raise ActionPlanValidationError(
                "ActionPlan confidence must be "
                "between 0.0 and 1.0."
            )

        return confidence

    @field_validator("parameters")
    @classmethod
    def _parameters_must_be_dict(
        cls,
        value: Any,
    ) -> Dict[str, Any]:
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise ActionPlanValidationError(
                "ActionPlan parameters must "
                "be a dictionary."
            )

        return dict(value)

    @field_validator("source")
    @classmethod
    def _source_must_be_non_empty_string(
        cls,
        value: Any,
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ActionPlanValidationError(
                "ActionPlan source must be a non-empty string."
            )

        return value

    @field_validator("task")
    @classmethod
    def _task_must_be_string(
        cls,
        value: Any,
    ) -> str:
        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan task must be a string."
            )

        return value

    @field_validator("reason")
    @classmethod
    def _reason_must_be_string(
        cls,
        value: Any,
    ) -> str:
        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan reason must be a string."
            )

        return value

    @field_validator("version")
    @classmethod
    def _version_must_be_string(
        cls,
        value: Any,
    ) -> str:
        if not isinstance(value, str):
            raise ActionPlanValidationError(
                "ActionPlan version must be a string."
            )

        return value

    # =========================================================
    # CONDITIONAL TARGET REQUIREMENT
    # =========================================================
    #
    # Expressed as a Pydantic model_validator (mode="after")
    # so the contract lives on the model itself instead of
    # being scattered across call-site ``if`` checks. The
    # ``TARGETLESS_OPERATIONS`` set is the single source of
    # truth that ``validate()`` and any downstream code now
    # both consult.

    @model_validator(mode="after")
    def _conditional_target_requirement(
        self,
    ) -> "ActionPlan":
        if (
            self.target is None
            and self.operation not in self.TARGETLESS_OPERATIONS
            and not self.parameters.get("requires_runtime_resolution")
            and not self.parameters.get("source_is_anaphoric")
            and not self.parameters.get("anaphoric_target")
        ):
            raise ActionPlanValidationError(
                "ActionPlan target is required "
                f"for operation '{self.operation}'."
            )

        return self

    # =========================================================
    # POSITIONAL CONSTRUCTION (backward compatibility)
    # =========================================================
    #
    # Pydantic ``BaseModel.__init__`` does not accept
    # positional field arguments by default, but several
    # existing tests and call sites historically built
    # ``ActionPlan("operation", "target")`` positionally,
    # matching the old ``@dataclass(frozen=True)`` signature.
    # This override restores that behaviour so every
    # pre-existing call site keeps working without
    # modification.

    def __init__(self, /, *args: Any, **kwargs: Any) -> None:
        # Item 14F (S9). The positional-argument support below and the
        # AuthorizationGrant guard used to be two independent pieces of
        # __init__, and only ONE of them ran the guard: the check lived
        # inside `if not args:`, so supplying a single positional
        # argument -- the historical `ActionPlan("op", "target")` form
        # this override exists to support -- skipped it entirely.
        #
        # That made the trusted adapter->executor channel forgeable from
        # any call site that happened to use positional syntax:
        #
        #     ActionPlan("file.delete", "C:/x", authorization={"forged": True})
        #
        # passed a dict straight into the field the keyword path
        # refuses, because the dictionary never had to survive an
        # isinstance check. The two paths have to agree, so positional
        # binding happens FIRST and the guard then runs once, below,
        # over whatever the merged keyword mapping contains.

        if args:
            positional_fields = (
                "operation",
                "target",
                "application",
                "task",
                "confidence",
                "parameters",
                "reason",
                "source",
                "version",
            )
            if len(args) > len(positional_fields):
                raise TypeError(
                    "ActionPlan.__init__ takes at most "
                    f"{len(positional_fields)} positional "
                    "arguments but "
                    f"{len(args)} were given."
                )

            bound = dict(zip(positional_fields, args))
            overlapping = set(bound).intersection(kwargs)
            if overlapping:
                raise TypeError(
                    "ActionPlan got both positional and keyword "
                    f"arguments for fields: {sorted(overlapping)}"
                )
            kwargs = {**bound, **kwargs}

        # AuthorizationGrant is validated by isinstance, not
        # coerced. Anything JSON-shaped is refused rather than
        # silently accepted, which is what makes this channel
        # structurally un-forgeable rather than merely
        # un-populated.
        grant = kwargs.get("authorization")
        if grant is not None and not _is_authorization_grant(grant):
            raise TypeError(
                "ActionPlan.authorization must be an "
                "AuthorizationGrant issued by "
                "issue_authorization_grant(). JSON-shaped values "
                "(dict, str, bool) are refused: this field is the "
                "trusted adapter->executor channel and cannot be "
                "populated from model input."
            )

        super().__init__(**kwargs)

    # =========================================================
    # VALIDATION
    # =========================================================

    def validate(
        self,
        *,
        supported_operations: Optional[Iterable[str]] = None,
        require_target: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        """
        Validate the ActionPlan against the legacy allow-list
        contract used by the executor and planner.

        Field-level invariants (string types, confidence
        range, conditional target requirement) are already
        enforced by Pydantic at construction time. This
        method exists for backward compatibility with the
        existing call sites that call ``plan.validate(...)``
        with a custom operation allow-list (the planner and
        the executor pass the full ``SUPPORTED_OPERATIONS``
        set) and a custom minimum confidence.
        """

        # =====================================================
        # SUPPORTED OPERATIONS
        # =====================================================

        allowed: FrozenSet[str]
        if supported_operations is not None:
            allowed = frozenset(supported_operations)
        else:
            allowed = self.APPLICATION_OPERATIONS

        if self.operation not in allowed:
            raise ActionPlanValidationError(
                f"Unsupported ActionPlan operation: "
                f"{self.operation}"
            )

        # =====================================================
        # REQUIRE_TARGET GATE
        # =====================================================
        #
        # Kept for backward compatibility: existing call sites
        # can still request a stricter require_target=True. The
        # Pydantic model_validator has already accepted the
        # canonical TARGETLESS_OPERATIONS cases at
        # construction time; this branch handles custom
        # in-line GUI ops the caller may want to add to the
        # allow-list at validation time only.

        if (
            require_target
            and self.target is None
            and self.operation not in self.TARGETLESS_OPERATIONS
        ):
            raise ActionPlanValidationError(
                "ActionPlan target is required."
            )

        # =====================================================
        # MINIMUM CONFIDENCE
        # =====================================================

        try:
            minimum = float(minimum_confidence)
        except (
            TypeError,
            ValueError,
        ) as error:
            raise ActionPlanValidationError(
                "Minimum confidence must be numeric."
            ) from error

        if not isfinite(minimum):
            raise ActionPlanValidationError(
                "Minimum confidence must be finite."
            )

        if not 0.0 <= minimum <= 1.0:
            raise ActionPlanValidationError(
                "Minimum confidence must be "
                "between 0.0 and 1.0."
            )

        if self.confidence < minimum:
            raise ActionPlanValidationError(
                "ActionPlan confidence "
                f"{self.confidence:.3f} is below the "
                f"required minimum of {minimum:.3f}."
            )

    # =========================================================
    # DECISION → ACTION PLAN
    # =========================================================

    @classmethod
    def from_decision(
        cls,
        decision: Dict[str, Any],
    ) -> "ActionPlan":
        """
        Convert a Level 3 workflow decision into an ActionPlan.

        No OS operation is performed.

        Compatibility rules:
            - Level 3 decisions are accepted.
            - Explicit non-OS modes are rejected.
            - Missing mode is accepted for backward compatibility.
            - Operation defaults are preserved.
        """

        if not isinstance(
            decision,
            dict,
        ):
            raise TypeError(
                "Decision must be a dictionary."
            )

        # ---------------------------------------------------------
        # LEVEL VALIDATION
        # ---------------------------------------------------------

        if decision.get("level") != 3:
            raise ValueError(
                "Only Level 3 decisions can be "
                "converted into an ActionPlan."
            )

        # ---------------------------------------------------------
        # MODE VALIDATION
        #
        # Older Level 3 decisions did not necessarily contain
        # "mode". Missing mode therefore remains compatible.
        #
        # Explicit non-OS modes are rejected.
        # ---------------------------------------------------------

        mode = decision.get("mode")

        if mode is not None and mode != "os":
            raise ValueError(
                "ActionPlan requires an OS workflow decision."
            )

        # ---------------------------------------------------------
        # OPERATION
        # ---------------------------------------------------------

        operation = decision.get("operation") or decision.get("intent") or "application.open"

        # ---------------------------------------------------------
        # TARGET
        # ---------------------------------------------------------

        target = decision.get(
            "target"
        )
        if isinstance(target, str) and not target.strip():
            target = None

        # ---------------------------------------------------------
        # APPLICATION
        # ---------------------------------------------------------

        application = decision.get(
            "application"
        )

        # ---------------------------------------------------------
        # TASK
        # ---------------------------------------------------------

        task = decision.get(
            "task",
            "",
        )

        # ---------------------------------------------------------
        # CONFIDENCE
        # ---------------------------------------------------------

        confidence = decision.get(
            "confidence",
            0.0,
        )

        # ---------------------------------------------------------
        # PARAMETERS
        # ---------------------------------------------------------

        parameters = decision.get(
            "parameters",
            {},
        )

        if parameters is None:
            parameters = {}

        if not isinstance(
            parameters,
            dict,
        ):
            raise TypeError(
                "Decision parameters must be a dictionary."
            )

        # ---------------------------------------------------------
        # REASON
        # ---------------------------------------------------------

        reason = decision.get(
            "reason",
            "",
        )

        # ---------------------------------------------------------
        # SOURCE
        # ---------------------------------------------------------

        source = decision.get(
            "source",
            "WorkflowDecisionEngine",
        )

        # ---------------------------------------------------------
        # VERSION
        # ---------------------------------------------------------

        version = decision.get(
            "version",
            "3.3.2",
        )

        # ---------------------------------------------------------
        # CREATE PLAN
        # ---------------------------------------------------------

        return cls(
            operation=operation,
            target=target,
            application=application,
            task=task,
            confidence=confidence,
            parameters=parameters,
            reason=reason,
            source=source,
            version=version,
        )

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        """
        Return a JSON-friendly representation.
        """

        return {
            "operation": self.operation,
            "target": self.target,
            "application": self.application,
            "task": self.task,
            "confidence": self.confidence,
            "parameters": dict(
                self.parameters
            ),
            "reason": self.reason,
            "source": self.source,
            "version": self.version,
        }

    # =========================================================
    # EXPLANATION
    # =========================================================

    def explain(
        self,
    ) -> str:
        """
        Human-readable explanation of intent.
        """

        target = (
            self.target
            or self.application
            or "unknown target"
        )

        return (
            "Genesis intends to perform "
            f"'{self.operation}' on "
            f"'{target}'. "
            f"Confidence: {self.confidence:.2f}."
        )


# =========================================================
# DATACLASS INTEROP INSTALLATION
# =========================================================
#
# After Pydantic has finished building the model, populate
# ``ActionPlan.__dataclass_fields__`` with a ``Field`` view
# for each declared field. This makes
# ``dataclasses.replace(plan, ...)`` (used by the production
# execution pipeline to rebuild resolved plans) accept the
# Pydantic instance without raising
# ``TypeError: replace() should be called on dataclass
# instances``.
#
# When ``dataclasses.replace`` runs:
#   * ``_is_dataclass_instance`` returns True because
#     ``__dataclass_fields__`` exists.
#   * For each field not in ``changes`` it reads via
#     ``getattr(obj, name)`` which works on Pydantic models.
#   * It calls ``cls(**changes)`` to construct the new
#     instance. ``ActionPlan.__init__`` accepts keyword
#     arguments and routes through the full Pydantic
#     validation pipeline, so the rebuilt plan is just as
#     safe as one built by hand.
from dataclasses import make_dataclass

# Build a tiny throwaway dataclass with the same field
# names so we can lift properly-named ``Field`` objects
# off of it (each Field needs ``name`` to be set, which
# is not the case for a ``field(default=None)`` literal).
_ActionPlan_dc_template = make_dataclass(
    "_ActionPlan_dc_template",
    [
        (name, object) for name in ActionPlan._DATACLASS_FIELD_NAMES
    ],
)
ActionPlan.__dataclass_fields__ = {
    f.name: f for f in _ActionPlan_dc_template.__dataclass_fields__.values()
}
del _ActionPlan_dc_template