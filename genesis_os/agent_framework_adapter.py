"""
Genesis OS - Agent Framework Adapter
===================================

Phase 2 of the UCCL roadmap.

This module is a thin translation layer between Microsoft Agent
Framework and Genesis's existing Level 3 execution pipeline.

Architectural rule (unchanged):

    Agent Framework
        |
        v
    AgentFrameworkAdapter  <-- THIS MODULE (thin boundary)
        |
        v
    ActionPlan (Pydantic-validated, per Phase 1)
        |
        v
    ActionExecutor.execute (Phase 0 verification-honest path)
        |
        v
    OSManager + verification_helpers

The adapter MUST NOT:

    - bypass the executor
    - reimplement validation / safety / dispatch
    - synthesize ``verified`` independently of ActionResult
    - substitute ``confirmed=True`` for a real confirmation flow
    - invent fields that aren't on the existing CapabilityDescriptor
    - silently auto-approve a destructive capability for the sake of
      a clean demo; every destructive call MUST pause for an
      explicit human approval token before the executor is reached

The adapter MUST:

    - read the CapabilityDescriptor from CapabilityRegistry
    - construct an ActionPlan from the tool arguments
    - call ``ActionExecutor.execute(plan)`` verbatim
    - return the ActionResult's real ``verified`` /
      ``verification_reason`` fields to the model
    - propagate safety / confirmation / verification failures
      honestly (so the model can react to them)

PoC scope (per ``phase2_agent_framework_adapter.md``):

    application.open
    gui.type_text
    document.create
    document.read
    browser.open_url

Horizontal expansion scope (per ``phase2_expansion.md``):

    document.search, document.compare, document.summarize,
    document.edit, document.transform, document.verify
    spreadsheet.inspect, spreadsheet.read, spreadsheet.sort,
    spreadsheet.filter, spreadsheet.calculate, spreadsheet.rank,
    spreadsheet.group_by, spreadsheet.aggregate, spreadsheet.compare
    browser.search, browser.extract, browser.find,
    browser.get_title, browser.get_url, browser.switch_tab,
    browser.open_tab, browser.close_tab, browser.get_tabs,
    browser.wait, browser.screenshot, browser.select,
    browser.download, browser.verify,
    browser.click, browser.type, browser.upload
    gui.paste_text
    file.copy, file.move

    Note: browser.click, browser.type, browser.upload now emit real
    ``element_found`` / ``verified`` signals from the provider layer
    (Phase 8 Browser Intelligence — post-state verification).
    - application.close (only ``taskkill /F`` implementation,
      no unsaved-changes guard - the risk-tiered confirmation
      gate is a future session)
    - destructive-tier capabilities (file.delete etc.)
    - PDF-creation capabilities (not implemented yet)

Note on scope-name aliases: the scope prompt lists user-facing
names such as ``browser.extract_text`` and ``browser.get_page_title``.
The canonical registry + executor IDs are the verb-only forms
(``browser.extract``, ``browser.get_title``). The adapter wires
the canonical IDs since that is what the executor dispatches
and the registry holds; the model reads the descriptor-derived
description which surfaces the natural-language action.

The expansion keeps the same five architectural invariants:
descriptor-derived description, real ``ActionExecutor`` routing,
real ``verified``/``verification_reason``, no fabricated
fields, and no bypass of the confirmation gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from pydantic import BaseModel

from .action_executor import ActionExecutor
from .action_plan import ActionPlan
from .action_result import ActionResult
from .capabilities import CapabilityDescriptor
from .capability_registry import CapabilityRegistry


logger = logging.getLogger("genesis_os.agent_framework_adapter")


# ============================================================
# PROOF-OF-CONCEPT CAPABILITY SET
# ============================================================

POC_CAPABILITIES: Tuple[str, ...] = (
    "application.open",
    "gui.type_text",
    "document.create",
    "document.read",
    "browser.open_url",
)


# ============================================================
# HORIZONTAL EXPANSION CAPABILITY SET
# ============================================================
#
# Phase 2 expansion wired these capabilities following the
# exact same pattern as the PoC.  Each entry below is the
# canonical registered capability ID (which is what the
# executor dispatches and the registry holds); the public
# tool name the model sees is the canonical form too.  See
# the module docstring for the scope-to-canonical alias map.
#
# All entries have been confirmed to:
#   1. exist in CapabilityRegistry,
#   2. be dispatched by ActionExecutor._dispatch,
#   3. report honest ``verified`` / ``verification_reason``
#      via the verification-honesty-sweep helpers
#      (verification_helpers.py).
#
# Note: browser.click / browser.type / browser.upload now emit
# real verification signals from the provider layer (Phase 8).
#   - application.close (taskkill /F, no unsaved-changes
#     guard; awaits the risk-tiered confirmation gate)
#   - destructive-tier capabilities
#   - PDF-creation capabilities (not implemented)

EXPANDED_CAPABILITIES: Tuple[str, ...] = (
    # --- document.* (verification-honest per sweep) ---
    "document.search",
    "document.compare",
    "document.summarize",
    "document.edit",
    "document.transform",
    "document.verify",
    # --- spreadsheet.* ---
    "spreadsheet.inspect",
    "spreadsheet.read",
    "spreadsheet.sort",
    "spreadsheet.filter",
    "spreadsheet.calculate",
    "spreadsheet.rank",
    "spreadsheet.group_by",
    "spreadsheet.aggregate",
    "spreadsheet.compare",
    # --- browser.* (excluding the excluded trio) ---
    "browser.search",
    "browser.extract",
    "browser.find",
    "browser.get_title",
    "browser.get_url",
    "browser.switch_tab",
    "browser.open_tab",
    "browser.close_tab",
    "browser.get_tabs",
    "browser.wait",
    "browser.screenshot",
    "browser.select",
    "browser.download",
    "browser.verify",
    "browser.click",
    # --- gui (paste only; type_text is already in PoC) ---
    "gui.paste_text",
    # --- file (non-destructive only) ---
    "file.copy",
    "file.move",
    # --- file (DESTRUCTIVE, second-batch scope) ---
    "file.delete",
    # --- application (DESTRUCTIVE conditional, second-batch scope) ---
    "application.close",
    # --- cleanup (DESTRUCTIVE, second-batch scope) ---
    "cleanup.empty_recycle_bin",
    # --- application intelligence ---
    "application.inspect",
    "application.list",
    # --- file intelligence (non-destructive) ---
    "file.inspect",
    "file.read",
    "file.search",
    "file.hash",
    "file.open",
    "file.create",
    # --- folder intelligence (non-destructive) ---
    "folder.inspect",
    "folder.open",
    "folder.create",
    # --- clipboard ---
    "clipboard.copy",
    "clipboard.paste",
    # --- notes ---
    "notes.create",
    "notes.list",
    # --- media ---
    "media.play_pause",
    "media.next",
    "media.previous",
    "media.stop",
    # --- volume ---
    "volume.up",
    "volume.down",
    "volume.mute_toggle",
    "volume.set",
    "volume.get",
    # --- display ---
    "display.brightness_set",
    "display.brightness_get",
    # --- hardware ---
    "hardware.battery",
    "hardware.stats",
    "hardware.storage",
    # --- system / network ---
    "system.status",
    "system.open_settings",
    "network.list_wifi",
    # --- process ---
    "process.list",
    "process.inspect",
    # --- screen ---
    "screen.capture",
    # --- web / daily ---
    "web.research",
    "web.weather",
    "time.world_clock",
    # --- math ---
    "math.evaluate",
    # --- window management ---
    "window.minimize_all",
    "window.restore",
    "window.show_desktop",
    # --- browser extras ---
    "browser.scroll",
    "browser.capabilities",
    # --- GUI extras ---
    "gui.focus_window",
    "gui.inspect_window",
    "gui.click",
    "gui.read_visible_text",
    "gui.select",
    "gui.scroll",
    "gui.keyboard_action",
    # --- data ---
    "data.inspect",
    "data.transform",
    # --- document create variants ---
    "document.create_csv",
    "document.create_json",
    "document.create_markdown",
    "document.inspect_intel",
    # --- cleanup read-only ---
    "cleanup.recycle_bin_query",
    # --- package read-only ---
    "package.search",
    # --- destructive / gated (third-batch scope) ---
    "file.rename",
    "folder.rename",
    "folder.move",
    "folder.delete",
    "folder.organize",
    "document.create_docx",
    "package.install",
    "package.uninstall",
    "network.connect_wifi",
    "workstation.lock",
    "application.window_list",
    "browser.get_page_state",
    "browser.type",
    "browser.upload",
    "document.create_pdf",
    "document.inspect",
    "file.watch",
    "gui.double_click",
    "gui.drag",
    "gui.hotkey",
    "gui.inspect_ui_tree",
    "gui.wait",
    "gui.wait_for_state",
    "gui.wait_for_window",
    "spreadsheet.add_column",
    "spreadsheet.create_from_dicts",
    "spreadsheet.update_cell",
)


# ============================================================
# DESTRUCTIVE / RISK-TIERED OPERATIONS
# ============================================================
#
# These capabilities are wired into the adapter as tools, but
# before each one is forwarded to ``ActionExecutor.execute`` the
# adapter performs a risk-tier pre-check (see
# ``AgentFrameworkAdapter._risk_tier_pre_check``).  The pre-check
# returns a structured ``confirmation_required`` ``ActionResult``
# that the model can read and react to by re-invoking the same
# tool with ``confirmed=True`` once the human has explicitly
# approved.  The adapter itself NEVER injects ``confirmed=True``
# (the ``TestDestructiveCapabilitiesRequireConfirmation`` class
# in ``test_phase2_destructive_capabilities.py`` pins that).
#
# Classification (per the roadmap addendum, do not blanket-group
# everything in this list as one tier):
#
#     ALWAYS_DESTRUCTIVE
#         The action mutates system state in a way that is
#         irreversible from the user's perspective; confirmation
#         is required unconditionally.
#
#     CONDITIONALLY_DESTRUCTIVE
#         The action is normally safe (reversible / no-op) but
#         can be destructive under a specific precondition.  The
#         adapter evaluates that precondition and only blocks
#         when the precondition is true.
#
# Naming the tiers is for clarity inside the adapter only; the
# security model and the executor's confirmation gate continue
# to be the single source of truth for the underlying risk
# classification.

ALWAYS_DESTRUCTIVE: FrozenSet[str] = frozenset({
    "file.delete",
    "folder.delete",
    "cleanup.empty_recycle_bin",
    "package.uninstall",
})


CONDITIONALLY_DESTRUCTIVE: FrozenSet[str] = frozenset({
    "application.close",
    "file.rename",
    "folder.rename",
    "folder.move",
    "folder.organize",
    "document.create_docx",
    "package.install",
    "network.connect_wifi",
    "workstation.lock",
})


ADAPTER_CAPABILITY_ALIASES: Dict[str, str] = {
    "application.focus": "gui.focus_window",
    "application.inspect_window_content": "gui.inspect_window",
    "browser.find_text": "browser.find",
    "document.compare_intel": "document.compare",
    "document.create_docx_intel": "document.create_docx",
    "document.create_txt": "document.create",
    "document.read_intel": "document.read",
    "document.search_intel": "document.search",
    "document.summarize_intel": "document.summarize",
    "filesystem.open": "file.open",
    "filesystem.search": "file.search",
    "spreadsheet.inspect_intel": "spreadsheet.inspect",
    "spreadsheet.read_intel": "spreadsheet.read",
    "weather.current": "web.weather",
}


def canonical_adapter_capability_id(capability_id: str) -> str:
    return ADAPTER_CAPABILITY_ALIASES.get(capability_id, capability_id)


# Window-title substrings that indicate the application has
# unsaved user state.  These are common, observable patterns
# across major Windows applications; the check is intentionally
# conservative - if ANY visible top-level window for the
# process matches one of these patterns, the adapter treats the
# close as destructive.  The cost of a false positive is a
# confirm prompt the user could skip; the cost of a false
# negative is silent data loss.

UNSAVED_TITLE_PATTERNS: Tuple[str, ...] = (
    "* ",
    " *",
    "[Modified]",
    "(Modified)",
    " - Modified",
    " — Modified",
    "Untitled",
    "Recovered",
    " (Recovered)",
)


# Process name substrings that NEVER carry user-saveable state
# in the first place.  Closing these is always a no-op from the
# user's perspective and MUST NOT be blocked by the precondition
# check (a false positive on these would be a UX regression -
# the user could not even close a Calculator window without
# confirming).

TRANSIENT_PROCESS_HINTS: Tuple[str, ...] = (
    "calculator", "calc.exe",
    "notepad", "stikynot",
    "clock", "msclock",
    "settings", "systemsettings",
)


# ============================================================
# EXPLICIT HUMAN-APPROVAL TOKEN GATE (high/critical risk)
# ============================================================
#
# Token format (documented contract):
#
#     HUMAN-APPROVE:<capability_id>:<nonce>
#
#   - ``HUMAN-APPROVE:`` literal prefix (proves the string came
#     from the human-approval flow, not a model hallucination).
#   - ``<capability_id>`` must EXACTLY equal the capability being
#     invoked (e.g. ``file.delete``).  Tokens are NOT reusable
#     across capabilities.
#   - ``<nonce>`` is an opaque human-session token of >= 4 chars
#     (e.g. ``7f3a``, ``2026-09-23-abc123``).  It binds the token
#     to one approval dialog so replay across sessions is
#     visible in logs.
#
# Examples:
#
#     HUMAN-APPROVE:file.delete:7f3a
#     HUMAN-APPROVE:cleanup.empty_recycle_bin:2026-09-23-abc123
#     HUMAN-APPROVE:application.close:reviewed-by-user-01
#     HUMAN-APPROVE:package.install:pip-ok-9f2c
#     HUMAN-APPROVE:package.uninstall:remove-ok-44de
#
# Callers pass the token either as the explicit
# ``approval_token`` kwarg on ``execute_capability`` /
# ``aexecute_capability`` / ``invoke_sequence`` items, or as
# ``arguments["approval_token"]`` (tool-call path).  If the
# token is missing or invalid for a gated capability, the
# adapter returns a structured ``confirmation_required``
# ``ActionResult`` with ``success=False, executed=False,
# verified=False`` and ``metadata["confirmation_required"]=True``
# WITHOUT calling the executor (do NOT execute).

APPROVAL_TOKEN_PREFIX = "HUMAN-APPROVE:"

# Capabilities with risk high/critical that require the explicit
# human-approval token.  This is ALWAYS_DESTRUCTIVE (all
# critical: file.delete, folder.delete, cleanup.empty_recycle_bin,
# package.uninstall) plus the two gated high/medium-risk mutating
# ops from the task scope (application.close, package.install).
# ``file.delete``, ``cleanup.empty_recycle_bin``,
# ``application.close``, ``package.install`` /
# ``package.uninstall`` are the pinned task scope; ``folder.delete``
# is included because it shares the same critical tier.
APPROVAL_REQUIRED_CAPABILITIES: FrozenSet[str] = frozenset(
    set(ALWAYS_DESTRUCTIVE)
    | {"application.close", "package.install", "browser.upload"}
)


def requires_approval_token(
    capability_id: str,
    arguments: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return True when ``capability_id`` needs an approval token.

    Driven by ``blast_radius`` (reversibility), NOT by ``risk_level``.
    The two disagree on 57 capabilities by design — they answer
    different questions — and ``risk_level`` must never be consulted
    for gating, or it would gate reversible operations like
    ``application.open`` and ``network.list_wifi``.

    The explicit ``APPROVAL_REQUIRED_CAPABILITIES`` set is retained and
    checked first, so the five capabilities already proven by Phase 2's
    adversarial battery keep behaving exactly as before. Membership in
    that set is what marks ``application.close`` as CONDITIONAL: its
    token is only demanded when the unsaved-changes evaluator
    escalates it, which is handled by the caller, not here.

    Everything else Tier 1 by blast radius is routed through the SAME
    ApprovalStore mechanism — same argument-hash binding, same
    single-use consumption. This widens coverage of the existing gate;
    it does not introduce a second one.
    """
    if capability_id in APPROVAL_REQUIRED_CAPABILITIES:
        return True
    try:
        from .blast_radius import (
            BlastRadius,
            resolve_blast_radius,
        )

        # Item 9B: resolve with the REAL arguments.
        #
        # This used to pass `{}`, so the tier was computed as though the
        # capability were being called with no arguments at all. The
        # executor resolves with the real ones
        # (action_executor._operation_requires_authorization passes
        # plan.parameters), and the two disagreed whenever escalation is
        # argument-dependent -- the workspace-boundary check being the
        # common case. Reproduced: for file.move to a destination outside
        # the workspace, this returned False while the executor returned
        # True. The adapter therefore forwarded a call the executor would
        # always refuse, and since the refusal carries no route to a grant,
        # that legitimate call was blocked forever.
        #
        # Omitting `arguments` entirely still resolves as before, so any
        # existing caller that genuinely has no arguments keeps its
        # current answer.
        return (
            resolve_blast_radius(
                capability_id,
                dict(arguments or {}),
            )
            is BlastRadius.IRREVERSIBLE_OR_OUTWARD
        )
    except Exception:
        # Fail closed: if the tier cannot be read, demand the token.
        return True


def is_valid_approval_token(
    token: Any, capability_id: str
) -> bool:
    """
    Validate an ``approval_token`` for ``capability_id``.

    Valid format: ``HUMAN-APPROVE:<capability_id>:<nonce>``
    where ``<nonce>`` is >= 4 chars after stripping.
    """
    if not isinstance(token, str):
        return False
    if not token.startswith(APPROVAL_TOKEN_PREFIX):
        return False
    remainder = token[len(APPROVAL_TOKEN_PREFIX):]
    # Split into "<capability_id>:<nonce>" — capability ids
    # themselves contain one dot, never a colon, so split on
    # the LAST colon to allow nonces that contain colons.
    if ":" not in remainder:
        return False
    cap_part, _, nonce = remainder.rpartition(":")
    if cap_part.strip() != capability_id:
        return False
    if len(nonce.strip()) < 4:
        return False
    return True


def _extract_approval_token(
    arguments: Optional[Mapping[str, Any]],
    explicit: Optional[str] = None,
) -> Optional[str]:
    """Prefer the explicit kwarg, fall back to arguments dict."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if arguments is not None:
        try:
            candidate = arguments.get("approval_token")  # type: ignore[attr-defined]
        except Exception:
            candidate = None
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _consume_approval_token(
    token: Optional[str],
    capability_id: str,
    arguments: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Consume an approval token. Returns the consumed record, or None.

    The consumed record is RETURNED rather than stashed on the module.
    It used to be assigned to a process-global ``_LAST_CONSUMED_APPROVAL``
    and read later by the plan builder, which meant one request's
    approval was visible to a different, later request: the record was
    not tied to the call that produced it, so concurrent requests could
    read each other's authority (a cross-request authorization leak).

    The token is single-use, so the grant must be minted from this same
    consumption -- returning it lets the caller thread it explicitly to
    the plan it belongs to. Nothing shared is left behind.
    """
    if not is_valid_approval_token(token, capability_id):
        return None
    try:
        from .approval_store import ApprovalStore

        return ApprovalStore.consume_token(
            token,
            arguments=dict(arguments or {}),
        )
    except (TypeError, ValueError):
        return None


# ============================================================
# CAPABILITY -> ADAPTER SCHEMA
# ============================================================
#
# Each capability maps to a JSON schema (Pydantic-style) the model
# must follow when calling the tool.  The schema is derived from
# the descriptor's ``supported_inputs`` and the dispatcher's
# accepted parameter keys (i.e. fields the executor reads via
# ``plan.parameters``); it is NOT invented, and every field on it
# is a real key the downstream executor will inspect.
#
# Field names match the keys already used inside
# ``ActionExecutor._dispatch`` and ``action_executor.py`` for the
# specific operation (e.g. ``text`` for gui.type_text, ``path`` /
# ``content`` / ``title`` for document.create, ``url`` for
# browser.open_url).  Keys whose values feed ``plan.target``
# (i.e. the primary identifier the executor forwards as ``t``)
# are listed under the schema's ``required`` list alongside
# any non-target inputs the executor requires.

_ADAPTER_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "application.open": {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": (
                    "Name of the desktop application to open "
                    "(e.g. 'notepad', 'chrome')."
                ),
            },
        },
        "required": ["application"],
    },
    "gui.type_text": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Text to type into the currently focused window."
                ),
            },
        },
        "required": ["text"],
    },
    "gui.paste_text": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Text to paste from the clipboard into the "
                    "currently focused window."
                ),
            },
        },
        "required": ["text"],
    },
    "document.create": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path for the new document "
                    "(e.g. 'C:\\\\Users\\\\me\\\\Desktop\\\\note.txt')."
                ),
            },
            "content": {
                "type": "string",
                "description": "Initial textual content of the document.",
            },
            "title": {
                "type": "string",
                "description": (
                    "Title used when the document type is docx; "
                    "ignored for plain text."
                ),
            },
        },
        "required": ["path"],
    },
    "document.create_pdf": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path for the new PDF document."
                ),
            },
            "title": {
                "type": "string",
                "description": "Title rendered at the top of the PDF.",
            },
            "content": {
                "type": "string",
                "description": "Body text rendered into the PDF.",
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["path"],
    },
    "document.read": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the document to read."
                ),
            },
        },
        "required": ["path"],
    },
    # --- document.* (expansion) ---
    "document.search": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the document to "
                    "search within."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Text query to search for in the document."
                ),
            },
        },
        "required": ["path", "query"],
    },
    "document.compare": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the first "
                    "(primary) document to compare."
                ),
            },
            "other_path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the second "
                    "document to compare against the primary."
                ),
            },
        },
        "required": ["path", "other_path"],
    },
    "document.summarize": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the document to "
                    "summarize."
                ),
            },
            "max_length": {
                "type": "integer",
                "description": (
                    "Optional maximum length (in characters) of "
                    "the generated summary. Omit for the "
                    "provider default."
                ),
            },
        },
        "required": ["path"],
    },
    "document.edit": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the document to "
                    "edit."
                ),
            },
            "find_text": {
                "type": "string",
                "description": "Text to locate in the document.",
            },
            "replace_text": {
                "type": "string",
                "description": "Replacement text.",
            },
        },
        "required": ["path", "find_text", "replace_text"],
    },
    "document.transform": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the source document."
                ),
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path where the transformed "
                    "document will be written."
                ),
            },
            "output_format": {
                "type": "string",
                "description": (
                    "Target format for the transformation "
                    "(e.g. 'txt', 'html', 'md')."
                ),
            },
        },
        "required": ["path", "output_path", "output_format"],
    },
    "document.verify": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the document to "
                    "verify."
                ),
            },
            "expected_content": {
                "type": "string",
                "description": (
                    "Optional content snippet the document is "
                    "expected to contain."
                ),
            },
            "expected_format": {
                "type": "string",
                "description": (
                    "Optional format the document is expected to "
                    "match (e.g. 'txt', 'json')."
                ),
            },
        },
        "required": ["path"],
    },
    # --- spreadsheet.* (expansion) ---
    "spreadsheet.inspect": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet "
                    "to inspect (csv / xlsx / etc.)."
                ),
            },
        },
        "required": ["path"],
    },
    "spreadsheet.read": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet "
                    "to read."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": (
                    "Optional name of the sheet to read. Defaults "
                    "to the first sheet when omitted."
                ),
            },
        },
        "required": ["path"],
    },
    "spreadsheet.sort": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the source "
                    "spreadsheet."
                ),
            },
            "column": {
                "type": "string",
                "description": (
                    "Column name to sort by."
                ),
            },
            "descending": {
                "type": "boolean",
                "description": (
                    "If true, sort in descending order. "
                    "Defaults to true."
                ),
            },
            "output": {
                "type": "string",
                "description": (
                    "Optional absolute filesystem path where the "
                    "sorted spreadsheet will be written."
                ),
            },
        },
        "required": ["path", "column"],
    },
    "spreadsheet.filter": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet "
                    "to filter."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to filter within.",
            },
            "column": {
                "type": "string",
                "description": "Column to filter on.",
            },
            "condition": {
                "type": "string",
                "description": (
                    "Comparison operator (e.g. 'equals', 'gt', "
                    "'lt', 'contains')."
                ),
            },
            "value": {
                "type": "string",
                "description": "Value to compare against.",
            },
        },
        "required": [
            "path", "sheet_name", "column", "condition", "value",
        ],
    },
    "spreadsheet.calculate": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to calculate on.",
            },
            "formula_column": {
                "type": "string",
                "description": (
                    "Name of the column where the calculated "
                    "values will be written."
                ),
            },
            "formula_template": {
                "type": "string",
                "description": (
                    "Formula template to apply per row."
                ),
            },
        },
        "required": [
            "path", "sheet_name", "formula_column", "formula_template",
        ],
    },
    "spreadsheet.rank": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to rank within.",
            },
            "rank_column": {
                "type": "string",
                "description": (
                    "Name of the column whose values determine "
                    "the rank."
                ),
            },
            "output": {
                "type": "string",
                "description": (
                    "Optional absolute filesystem path where the "
                    "ranked spreadsheet will be written."
                ),
            },
        },
        "required": ["path", "sheet_name", "rank_column"],
    },
    "spreadsheet.group_by": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to group within.",
            },
            "column": {
                "type": "string",
                "description": "Column to group on.",
            },
            "agg_column": {
                "type": "string",
                "description": (
                    "Optional column to aggregate over within "
                    "each group."
                ),
            },
            "operation": {
                "type": "string",
                "description": (
                    "Aggregation operation to apply "
                    "(e.g. 'count', 'sum', 'avg'). "
                    "Defaults to 'count'."
                ),
            },
        },
        "required": ["path", "sheet_name", "column"],
    },
    "spreadsheet.aggregate": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the spreadsheet."
                ),
            },
            "sheet_name": {
                "type": "string",
                "description": "Sheet name to aggregate over.",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of column names to aggregate."
                ),
            },
            "operation": {
                "type": "string",
                "description": (
                    "Aggregation operation to apply "
                    "(e.g. 'sum', 'avg', 'min', 'max'). "
                    "Defaults to 'sum'."
                ),
            },
        },
        "required": ["path", "sheet_name", "columns"],
    },
    "spreadsheet.compare": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the first "
                    "spreadsheet (primary)."
                ),
            },
            "other_path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the second "
                    "spreadsheet to compare against."
                ),
            },
            "sheet1": {
                "type": "string",
                "description": (
                    "Sheet name in the primary spreadsheet."
                ),
            },
            "sheet2": {
                "type": "string",
                "description": (
                    "Sheet name in the secondary spreadsheet."
                ),
            },
        },
        "required": ["path", "other_path", "sheet1", "sheet2"],
    },
    # --- browser.* (expansion; excluded trio omitted) ---
    "browser.open_url": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "Fully qualified URL (including scheme) to open in "
                    "the default browser."
                ),
            },
        },
        "required": ["url"],
    },
    "browser.search": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query to dispatch to the configured "
                    "search engine."
                ),
            },
            "engine": {
                "type": "string",
                "description": (
                    "Optional search engine (e.g. 'google'). "
                    "Defaults to 'google'."
                ),
            },
        },
        "required": ["query"],
    },
    "browser.extract": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": (
                    "CSS / XPath / text selector identifying the "
                    "element whose text content should be extracted."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["selector"],
    },
    "browser.find": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to find on the page.",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["text"],
    },
    "browser.get_title": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
    },
    "browser.get_url": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
    },
    "browser.switch_tab": {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": (
                    "Zero-based index of the tab to switch to."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["index"],
    },
    "browser.open_tab": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "Optional URL to open in the new tab. When "
                    "omitted a blank tab is opened."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Browser session identifier. Defaults to "
                    "'default' when omitted by the caller; the "
                    "adapter always supplies it so the action "
                    "target is unambiguous."
                ),
            },
        },
        "required": ["session_id"],
    },
    "browser.close_tab": {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": (
                    "Optional zero-based index of the tab to "
                    "close. When omitted the current tab is closed."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Browser session identifier. Defaults to "
                    "'default' when omitted by the caller; the "
                    "adapter always supplies it so the action "
                    "target is unambiguous."
                ),
            },
        },
        "required": ["session_id"],
    },
    "browser.get_tabs": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
    },
    "browser.wait": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": (
                    "CSS / XPath selector identifying the "
                    "element to wait for."
                ),
            },
            "timeout": {
                "type": "number",
                "description": (
                    "Maximum seconds to wait for the element. "
                    "Defaults to 10."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["selector"],
    },
    "browser.screenshot": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path where the PNG "
                    "screenshot will be written."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["path"],
    },
    "browser.select": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": (
                    "CSS / XPath selector identifying the "
                    "<select> element."
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "Optional value attribute to select."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Optional visible label to select."
                ),
            },
            "index": {
                "type": "integer",
                "description": (
                    "Optional zero-based index of the option "
                    "to select."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["selector"],
    },
    "browser.download": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of the file to download.",
            },
            "save_path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path where the "
                    "downloaded file will be written."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
        "required": ["url"],
    },
    "browser.verify": {
        "type": "object",
        "properties": {
            "expected_url": {
                "type": "string",
                "description": (
                    "Optional URL the page is expected to match."
                ),
            },
            "expected_title_contains": {
                "type": "string",
                "description": (
                    "Optional substring the page title is "
                    "expected to contain."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional browser session identifier. "
                    "Defaults to 'default'."
                ),
            },
        },
    },
    # --- file.* (non-destructive; expansion) ---
    "file.copy": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the source file."
                ),
            },
            "destination": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the destination "
                    "file (the copy target)."
                ),
            },
        },
        "required": ["path", "destination"],
    },
    "file.move": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the source file."
                ),
            },
            "destination": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the destination "
                    "after the move."
                ),
            },
        },
        "required": ["path", "destination"],
    },
    # --- file.delete (DESTRUCTIVE; gated by the adapter-level
    #     risk-tier pre-check before reaching the executor) ---
    "file.delete": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute filesystem path of the file to "
                    "permanently delete."
                ),
            },
            "approval_token": {
                "type": "string",
                "description": (
                    "Explicit human-approval token, format "
                    "'HUMAN-APPROVE:file.delete:<nonce>' "
                    "(nonce >= 4 chars). Required; without a "
                    "valid token the call bounces with "
                    "confirmation_required and is NOT executed."
                ),
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["path"],
    },
    # --- application.close (CONDITIONALLY DESTRUCTIVE; gated
    #     only when the unsaved-changes precondition is active) ---
    "application.close": {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": (
                    "Name of the desktop application to close "
                    "(e.g. 'notepad', 'chrome')."
                ),
            },
            "approval_token": {
                "type": "string",
                "description": (
                    "Explicit human-approval token, format "
                    "'HUMAN-APPROVE:application.close:<nonce>'. "
                    "Required when the unsaved-changes "
                    "precondition is active or when the caller "
                    "wants to force-close."
                ),
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["application"],
    },
    # --- cleanup.empty_recycle_bin (DESTRUCTIVE; gated by
    #     the adapter-level risk-tier pre-check) ---
    "cleanup.empty_recycle_bin": {
        "type": "object",
        "properties": {
            "approval_token": {
                "type": "string",
                "description": (
                    "Explicit human-approval token, format "
                    "'HUMAN-APPROVE:cleanup.empty_recycle_bin:"
                    "<nonce>'. Required; without it the call "
                    "bounces with confirmation_required."
                ),
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
    },
    # --- browser.click (non-destructive; real element_found signal
    #     from provider layer — Phase 8 verification) ---
    "browser.click": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": (
                    "CSS / XPath / text selector identifying the "
                    "element to click."
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Browser session identifier. Defaults to "
                    "'default' when omitted by the caller; the "
                    "adapter always supplies it."
                ),
            },
        },
        "required": ["session_id"],
    },
    # --- application intelligence ---
    "application.inspect": {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "Name of the application to inspect.",
            },
        },
        "required": ["application"],
    },
    "application.list": {
        "type": "object",
        "properties": {},
    },
    # --- file intelligence ---
    "file.inspect": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to inspect.",
            },
        },
        "required": ["path"],
    },
    "file.read": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to read.",
            },
        },
        "required": ["path"],
    },
    "file.search": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to search in.",
            },
            "query": {
                "type": "string",
                "description": "Filename pattern or search query.",
            },
        },
        "required": ["query"],
    },
    "file.hash": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to hash.",
            },
            "algorithm": {
                "type": "string",
                "description": "Hash algorithm (sha256, md5, etc.).",
            },
        },
        "required": ["path"],
    },
    "file.open": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to open with default app.",
            },
        },
        "required": ["path"],
    },
    "file.create": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new file.",
            },
            "content": {
                "type": "string",
                "description": "Initial text content.",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite if exists.",
            },
        },
        "required": ["path"],
    },
    # --- folder intelligence ---
    "folder.inspect": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to inspect.",
            },
        },
        "required": ["path"],
    },
    "folder.open": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to open in explorer.",
            },
        },
        "required": ["path"],
    },
    "folder.create": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new folder.",
            },
        },
        "required": ["path"],
    },
    # --- clipboard ---
    "clipboard.copy": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to copy to clipboard.",
            },
        },
        "required": ["text"],
    },
    "clipboard.paste": {
        "type": "object",
        "properties": {},
    },
    # --- notes ---
    "notes.create": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text content of the note.",
            },
        },
        "required": ["text"],
    },
    "notes.list": {
        "type": "object",
        "properties": {},
    },
    # --- media ---
    "media.play_pause": {
        "type": "object",
        "properties": {},
    },
    "media.next": {
        "type": "object",
        "properties": {},
    },
    "media.previous": {
        "type": "object",
        "properties": {},
    },
    "media.stop": {
        "type": "object",
        "properties": {},
    },
    # --- volume ---
    "volume.up": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "integer",
                "description": "Number of steps to increase.",
            },
        },
    },
    "volume.down": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "integer",
                "description": "Number of steps to decrease.",
            },
        },
    },
    "volume.mute_toggle": {
        "type": "object",
        "properties": {
            "mute": {
                "type": "boolean",
                "description": "True to mute, false to unmute, omit to toggle.",
            },
        },
    },
    "volume.set": {
        "type": "object",
        "properties": {
            "percent": {
                "type": "string",
                "description": "Volume percentage (0-100).",
            },
        },
        "required": ["percent"],
    },
    "volume.get": {
        "type": "object",
        "properties": {},
    },
    # --- display ---
    "display.brightness_set": {
        "type": "object",
        "properties": {
            "percent": {
                "type": "string",
                "description": "Brightness percentage (0-100).",
            },
            "direction": {
                "type": "string",
                "description": "Direction: 'up' or 'down'.",
            },
        },
    },
    "display.brightness_get": {
        "type": "object",
        "properties": {},
    },
    # --- hardware ---
    "hardware.battery": {
        "type": "object",
        "properties": {},
    },
    "hardware.stats": {
        "type": "object",
        "properties": {},
    },
    "hardware.storage": {
        "type": "object",
        "properties": {},
    },
    # --- system / network ---
    "system.status": {
        "type": "object",
        "properties": {},
    },
    "system.open_settings": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Settings page (e.g. 'bluetooth', 'wifi', 'display').",
            },
        },
        "required": ["target"],
    },
    "network.list_wifi": {
        "type": "object",
        "properties": {},
    },
    # --- process ---
    "process.list": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Filter by process name (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Max processes to return.",
            },
        },
    },
    "process.inspect": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Process name or PID to inspect.",
            },
        },
        "required": ["target"],
    },
    # --- screen ---
    "screen.capture": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Output path for the screenshot (optional).",
            },
        },
    },
    # --- web / daily ---
    "web.research": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return.",
            },
        },
        "required": ["query"],
    },
    "web.weather": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name for weather lookup.",
            },
        },
        "required": ["city"],
    },
    "time.world_clock": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name for time lookup.",
            },
        },
        "required": ["city"],
    },
    # --- math ---
    "math.evaluate": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression to evaluate.",
            },
        },
        "required": ["expression"],
    },
    # --- window management ---
    "window.minimize_all": {
        "type": "object",
        "properties": {},
    },
    "window.restore": {
        "type": "object",
        "properties": {},
    },
    "window.show_desktop": {
        "type": "object",
        "properties": {},
    },
    # --- browser extras ---
    "browser.scroll": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "Scroll direction: 'up' or 'down'.",
            },
            "amount": {
                "type": "integer",
                "description": "Number of scroll ticks.",
            },
            "session_id": {
                "type": "string",
                "description": "Browser session id.",
            },
        },
        "required": ["session_id"],
    },
    "browser.capabilities": {
        "type": "object",
        "properties": {},
    },
    # --- GUI extras ---
    "gui.focus_window": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Window title pattern to focus.",
            },
        },
        "required": ["target"],
    },
    "gui.inspect_window": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Window title pattern to inspect.",
            },
        },
        "required": ["target"],
    },
    "gui.click": {
        "type": "object",
        "properties": {
            "x": {
                "type": "integer",
                "description": "Screen X coordinate.",
            },
            "y": {
                "type": "integer",
                "description": "Screen Y coordinate.",
            },
        },
        "required": ["x", "y"],
    },
    "gui.read_visible_text": {
        "type": "object",
        "properties": {},
    },
    "gui.select": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Text to select.",
            },
        },
    },
    "gui.scroll": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "Scroll direction: 'up' or 'down'.",
            },
            "amount": {
                "type": "integer",
                "description": "Number of scroll ticks.",
            },
        },
    },
    "gui.keyboard_action": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to press (e.g. 'enter', 'ctrl+c').",
            },
        },
        "required": ["key"],
    },
    # --- data ---
    "data.inspect": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the data file.",
            },
        },
        "required": ["path"],
    },
    "data.transform": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Source file path.",
            },
            "target_format": {
                "type": "string",
                "description": "Desired output format.",
            },
            "output": {
                "type": "string",
                "description": "Output file path.",
            },
        },
        "required": ["source", "target_format"],
    },
    # --- document create variants ---
    "document.create_csv": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new CSV.",
            },
            "content": {
                "type": "string",
                "description": "CSV content.",
            },
        },
        "required": ["path"],
    },
    "document.create_json": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new JSON.",
            },
            "content": {
                "type": "string",
                "description": "JSON content.",
            },
        },
        "required": ["path"],
    },
    "document.create_markdown": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new Markdown.",
            },
            "content": {
                "type": "string",
                "description": "Markdown content.",
            },
        },
        "required": ["path"],
    },
    "document.inspect_intel": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the document.",
            },
        },
        "required": ["path"],
    },
    # --- cleanup read-only ---
    "cleanup.recycle_bin_query": {
        "type": "object",
        "properties": {},
    },
    # --- package read-only ---
    "package.search": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Package search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return.",
            },
        },
        "required": ["query"],
    },
    # --- destructive / gated ---
    "file.rename": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file.",
            },
            "new_name": {
                "type": "string",
                "description": "New filename.",
            },
        },
        "required": ["path", "new_name"],
    },
    "folder.rename": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the folder.",
            },
            "new_name": {
                "type": "string",
                "description": "New folder name.",
            },
        },
        "required": ["path", "new_name"],
    },
    "folder.move": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the folder.",
            },
            "destination": {
                "type": "string",
                "description": "Destination directory.",
            },
        },
        "required": ["path", "destination"],
    },
    "folder.delete": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the folder.",
            },
            # folder.delete is Tier 1 (irreversible_or_outward) but was
            # NOT in the original approval-token set, so its schema
            # never exposed the field that opens the gate. Without this
            # the capability is permanently blocked: the gate demands a
            # token no caller can supply.
            "approval_token": {
                "type": "string",
                "description": (
                    "Human-approval token, format "
                    "'HUMAN-APPROVE:folder.delete:<nonce>'. Required; "
                    "without it the call is refused with "
                    "confirmation_required and nothing is executed."
                ),
            },
        },
        "required": ["path"],
    },
    "folder.organize": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the folder to organize.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview changes without applying.",
            },
            # Tier 1 by blast radius; schema must expose the gate.
            "approval_token": {
                "type": "string",
                "description": (
                    "Human-approval token, format "
                    "'HUMAN-APPROVE:folder.organize:<nonce>'. Required; "
                    "without it the call is refused and nothing is "
                    "applied."
                ),
            },
        },
        "required": ["path"],
    },
    "document.create_docx": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new docx.",
            },
            "title": {
                "type": "string",
                "description": "Document title.",
            },
            "sections": {
                "type": "array",
                "description": "Document sections.",
            },
        },
        "required": ["path"],
    },
    "package.install": {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name to install.",
            },
            "approval_token": {
                "type": "string",
                "description": (
                    "Explicit human-approval token, format "
                    "'HUMAN-APPROVE:package.install:<nonce>'. "
                    "Required; without it the call bounces "
                    "with confirmation_required."
                ),
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["package"],
    },
    "package.uninstall": {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name to uninstall.",
            },
            "approval_token": {
                "type": "string",
                "description": (
                    "Explicit human-approval token, format "
                    "'HUMAN-APPROVE:package.uninstall:<nonce>'. "
                    "Required; without it the call bounces "
                    "with confirmation_required."
                ),
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["package"],
    },
    "network.connect_wifi": {
        "type": "object",
        "properties": {
            "ssid": {
                "type": "string",
                "description": "Wi-Fi network name.",
            },
            "password": {
                "type": "string",
                "description": "Wi-Fi password.",
            },
            # Tier 1 by blast radius (reconnection is not guaranteed in
            # every network environment); schema must expose the gate.
            "approval_token": {
                "type": "string",
                "description": (
                    "Human-approval token, format "
                    "'HUMAN-APPROVE:network.connect_wifi:<nonce>'. "
                    "Required; without it the call is refused and the "
                    "network is not touched."
                ),
            },
        },
        "required": ["ssid"],
    },
    "application.window_list": {
        "type": "object",
        "properties": {},
    },
    "browser.get_page_state": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": ["string", "null"],
                "description": "Browser session identifier; null uses the default session.",
            },
        },
    },
    "browser.type": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS / XPath / text selector for the input element.",
            },
            "text": {
                "type": "string",
                "description": "Text to type into the element.",
            },
            "session_id": {
                "type": "string",
                "description": "Browser session identifier.",
            },
        },
        "required": ["selector", "text"],
    },
    "browser.upload": {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS / XPath / text selector for the file input.",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path of the local file to upload.",
            },
            "session_id": {
                "type": "string",
                "description": "Browser session identifier.",
            },
            "approval_token": {
                "type": "string",
                "description": "Human-approval token, format 'HUMAN-APPROVE:browser.upload:<nonce>'.",
            },
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4).
            # It is no longer an authority anywhere, and with
            # additionalProperties=False advertising it only invited
            # callers to send a flag that does nothing. Attack A6
            # now fails at the schema with a TypeError.
        },
        "required": ["selector", "file_path"],
    },
    "document.inspect": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the document to inspect.",
            },
        },
        "required": ["path"],
    },
    "file.watch": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the file or folder to watch.",
            },
            "event": {
                "type": "string",
                "description": "Filesystem event name, such as 'modified'.",
            },
        },
        "required": ["path"],
    },
    "gui.double_click": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Screen X coordinate."},
            "y": {"type": "integer", "description": "Screen Y coordinate."},
        },
        "required": ["x", "y"],
    },
    "gui.drag": {
        "type": "object",
        "properties": {
            "start_x": {"type": "integer", "description": "Starting screen X coordinate."},
            "start_y": {"type": "integer", "description": "Starting screen Y coordinate."},
            "end_x": {"type": "integer", "description": "Ending screen X coordinate."},
            "end_y": {"type": "integer", "description": "Ending screen Y coordinate."},
            "duration": {"type": "number", "description": "Drag duration in seconds."},
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4); see above.
        },
        "required": ["start_x", "start_y", "end_x", "end_y"],
    },
    "gui.hotkey": {
        "type": "object",
        "properties": {
            "keys": {"type": "string", "description": "Keyboard shortcut, such as 'ctrl+s'."},
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4); see above.
        },
        "required": ["keys"],
    },
    "gui.inspect_ui_tree": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Window title pattern whose UI tree should be inspected."},
        },
        "required": ["target"],
    },
    "gui.wait": {
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "Seconds to wait."},
        },
    },
    "gui.wait_for_state": {
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "State condition to wait for."},
            "timeout": {"type": "number", "description": "Maximum wait time in seconds."},
        },
        "required": ["condition"],
    },
    "gui.wait_for_window": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Window title pattern to wait for."},
            "timeout": {"type": "number", "description": "Maximum wait time in seconds."},
            "poll_interval": {"type": "number", "description": "Polling interval in seconds."},
        },
        "required": ["target"],
    },
    "spreadsheet.add_column": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute workbook path."},
            "sheet_name": {"type": "string", "description": "Worksheet name."},
            "column_name": {"type": "string", "description": "Name of the column to add."},
            "values": {"type": "array", "items": {}, "description": "Values for the new column."},
            "output": {"type": "string", "description": "Optional output workbook path."},
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4); see above.
        },
        "required": ["path", "column_name"],
    },
    "spreadsheet.create_from_dicts": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute output workbook path."},
            "data": {"type": "array", "items": {"type": "object"}, "description": "Row dictionaries to write."},
            "sheet_name": {"type": "string", "description": "Name of the created worksheet."},
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4); see above.
        },
        "required": ["path", "data"],
    },
    "spreadsheet.update_cell": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute workbook path."},
            "sheet_name": {"type": "string", "description": "Worksheet name."},
            "row": {"type": "integer", "description": "Zero-based or provider-defined row index."},
            "column": {"type": "string", "description": "Column name or identifier."},
            "value": {"description": "New cell value."},
            "output": {"type": "string", "description": "Optional output workbook path."},
            # LEGACY confirmed REMOVED 2026-10-08 (F5 step 4); see above.
        },
        "required": ["path", "row", "column", "value"],
    },
    "weather.current": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City for current weather."},
        },
        "required": ["city"],
    },
    "workstation.lock": {
        "type": "object",
        "properties": {
            # Tier 1 by blast radius: Genesis cannot reverse a lock it
            # holds no password for. Previously this schema had NO
            # properties at all, so the capability demanded a token no
            # caller could possibly supply — a gate with no key.
            "approval_token": {
                "type": "string",
                "description": (
                    "Human-approval token, format "
                    "'HUMAN-APPROVE:workstation.lock:<nonce>'. Required; "
                    "without it the workstation is not locked."
                ),
            },
        },
    },
}


# ============================================================
# RESULT PARSER
# ============================================================
#
# Agent Framework wraps the tool return value as ``list[Content]``
# via ``FunctionTool.parse_result`` so the model receives a clean
# text payload that includes the REAL ``verified`` /
# ``verification_reason`` from ``ActionResult``.  The model can
# then react honestly - "verified True" is not just "success True".

def _action_result_to_text(result: ActionResult) -> str:
    """
    Render an ActionResult as a JSON string the model can read.

    Includes the full action result envelope so the model can
    observe ``success`` / ``executed`` / ``verified`` /
    ``verification_reason`` / ``status`` / ``error`` - the same
    fields the verification-honesty sweep binds to real
    post-state signals.  The text is JSON so downstream tooling
    can parse it deterministically.
    """

    payload = result.to_dict() if hasattr(result, "to_dict") else asdict(result)

    return json.dumps(payload, default=str, sort_keys=True)


# ============================================================
# ROUTING HELPERS
# ============================================================


def _build_action_plan(
    capability_id: str,
    arguments: Mapping[str, Any],
    consumed_approval: Optional[Dict[str, Any]] = None,
) -> ActionPlan:
    """
    Translate a tool call's arguments into the ActionPlan shape
    that ``ActionExecutor.execute`` expects.

    The mapping is purely a 1-to-1 transformation from each
    capability's supported inputs (already known to the executor)
    to ``ActionPlan.parameters`` / ``target`` / ``application``.
    No new logic is introduced here.

    ``consumed_approval`` is the ApprovalStore record THIS call just
    consumed, passed explicitly so the grant is minted from this
    request's own approval and never from one left over from another
    request. It is never read from module state.
    """

    capability_id = canonical_adapter_capability_id(capability_id)

    def _clean_str(value: Any) -> str:
        return str(value or "").strip()

    # Approval authority (2026-10-15): `confirmed` is NO LONGER forwarded
    # or promoted here.
    #
    # Previously this helper copied a CALLER-SUPPLIED
    # `arguments["confirmed"]` into the plan, and promoted
    # `params["confirmed"] = True` whenever a token looked syntactically
    # valid. Both made `plan.parameters["confirmed"]` a second,
    # model-reachable authority channel: `arguments` is tool-call JSON,
    # so a model could set `confirmed: true` and be believed.
    #
    # The ONLY authority now is a validated `approval_token` and the
    # AuthorizationGrant minted from its consumption. The token is still
    # forwarded to the plan (the executor reads it), and the grant is
    # still minted, so the authorized path is unchanged.
    def _runtime_tokens(params: Dict[str, Any]) -> Dict[str, Any]:
        if "approval_token" in arguments:
            token_val = arguments["approval_token"]
            if isinstance(token_val, str) and token_val.strip():
                params["approval_token"] = token_val.strip()
                # Mint the trusted AuthorizationGrant from this call's
                # own consumed approval. Minting consumes a real,
                # argument-hash-bound approval, so it cannot grant
                # authority the token route has not already granted —
                # and if it fails, no grant is attached and the executor
                # blocks the Tier 1 plan. Fails closed.
                try:
                    if is_valid_approval_token(
                        token_val.strip(), capability_id
                    ):
                        try:
                            from .authorization_grant import (
                                grant_from_consumed_record,
                            )

                            # The record comes from THIS call's own
                            # token consumption, threaded in by the
                            # caller. It used to be read from a module
                            # global, so a previous request's approval
                            # could satisfy this one.
                            record = consumed_approval
                            if record is None:
                                raise RuntimeError(
                                    "no consumed approval available"
                                )
                            params["_authorization_grant"] = (
                                grant_from_consumed_record(
                                    operation=capability_id,
                                    # MUST be the ORIGINAL tool-call
                                    # arguments, not `params`: the
                                    # approval was bound to those.
                                    arguments={
                                        key: value
                                        for key, value in arguments.items()
                                        if key != "approval_token"
                                    },
                                    record=record,
                                )
                            )
                        except Exception:
                            params.pop("_authorization_grant", None)
                except Exception:
                    pass
        return params

    if capability_id == "application.open":
        application = _clean_str(arguments.get("application"))
        return ActionPlan(
            operation="application.open",
            target=application or None,
            application=application or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.type_text":
        # gui.type_text is in ``TARGETLESS_OPERATIONS`` so target=None
        # is the canonical empty-target shape.
        text = arguments.get("text") or ""
        return ActionPlan(
            operation="gui.type_text",
            target=None,
            parameters=_runtime_tokens({"text": str(text)}),
            confidence=1.0,
        )

    if capability_id == "gui.paste_text":
        # Same code path as gui.type_text - targetless,
        # runtime-focus-resolver picks the focused window.
        text = arguments.get("text") or ""
        return ActionPlan(
            operation="gui.paste_text",
            target=None,
            parameters=_runtime_tokens({"text": str(text)}),
            confidence=1.0,
        )

    if capability_id == "document.create":
        # Phase 0 / Level 3 dispatch routes ``document.create`` to
        # ``document.create_txt`` (write a real text file via
        # ``doc_intel``).  Title is forwarded so a docx shape still
        # carries its canonical key.
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {
            "doc_type": "txt",
            "content": arguments.get("content") or "",
        }
        title = arguments.get("title")
        if isinstance(title, str) and title.strip():
            params["title"] = title.strip()
        return ActionPlan(
            operation="document.create_txt",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "document.read":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.read",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "document.search":
        # Executor dispatches: doc_search(t, p.get("query", "")).
        # The public name the model sees is ``document.search``,
        # but the canonical registered capability id (and the
        # operation name the executor's safety policy /
        # dispatch table consume) is ``document.search_intel``.
        # Forward the registered name as ``operation`` so the
        # safety policy recognises the call; the canonical
        # descriptor lookup (in ``describe_capability``) already
        # resolves the alias to ``document.search_intel``, so
        # the description, provider and risk-level fields stay
        # consistent with the registry.
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.search_intel",
            target=path or None,
            parameters=_runtime_tokens(
                {"query": str(arguments.get("query") or "")}
            ),
            confidence=1.0,
        )

    if capability_id == "document.compare":
        # Executor dispatches: doc_compare(t, p.get("other_path", "")).
        # ``t`` is plan.target = path1, parameters carry path2.
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.compare",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "other_path": _clean_str(
                        arguments.get("other_path")
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "document.summarize":
        # Executor dispatches: doc_summarize(t, max_length=p.get("max_length")).
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {}
        max_length = arguments.get("max_length")
        if max_length is not None:
            params["max_length"] = int(max_length)
        return ActionPlan(
            operation="document.summarize",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "document.edit":
        # Executor dispatches: doc_edit(t, p.get("find_text", ""),
        #                                p.get("replace_text", "")).
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.edit",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "find_text": str(arguments.get("find_text") or ""),
                    "replace_text": str(
                        arguments.get("replace_text") or ""
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "document.transform":
        # Executor dispatches: doc_transform(t, p.get("output_path", ""),
        #                                   p.get("output_format", "txt")).
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.transform",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "output_path": _clean_str(
                        arguments.get("output_path")
                    ),
                    "output_format": _clean_str(
                        arguments.get("output_format") or "txt"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "document.verify":
        # Executor dispatches: doc_verify(t,
        #     expected_content=p.get("expected_content"),
        #     expected_format=p.get("expected_format")).
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {}
        ec = arguments.get("expected_content")
        if isinstance(ec, str) and ec.strip():
            params["expected_content"] = ec
        ef = arguments.get("expected_format")
        if isinstance(ef, str) and ef.strip():
            params["expected_format"] = ef
        return ActionPlan(
            operation="document.verify",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    # --- spreadsheet.* ---

    if capability_id == "spreadsheet.inspect":
        # Executor dispatches: sheet_inspect(t).
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.inspect",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.read":
        # Executor dispatches: sheet_read(t, sheet_name=p.get("sheet_name")).
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {}
        sn = arguments.get("sheet_name")
        if isinstance(sn, str) and sn.strip():
            params["sheet_name"] = sn
        return ActionPlan(
            operation="spreadsheet.read",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.sort":
        # Executor dispatches:
        #     sort_spreadsheet(t, p.get("column", ""),
        #         descending=bool(p.get("descending", True)),
        #         output=p.get("output"), confirmed=True)
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {
            "column": str(arguments.get("column") or ""),
        }
        if "descending" in arguments:
            params["descending"] = bool(arguments.get("descending"))
        output = arguments.get("output")
        if isinstance(output, str) and output.strip():
            params["output"] = output
        return ActionPlan(
            operation="spreadsheet.sort",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.filter":
        # Executor dispatches:
        #     sheet_filter(t, p.get("sheet_name", ""),
        #         p.get("column", ""), p.get("condition", "equals"),
        #         p.get("value", ""))
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.filter",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet_name": _clean_str(arguments.get("sheet_name")),
                    "column": _clean_str(arguments.get("column")),
                    "condition": _clean_str(
                        arguments.get("condition") or "equals"
                    ),
                    "value": str(arguments.get("value") or ""),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.calculate":
        # Executor dispatches:
        #     sheet_calculate(t, p.get("sheet_name", ""),
        #         p.get("formula_column", ""),
        #         p.get("formula_template", ""))
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.calculate",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet_name": _clean_str(arguments.get("sheet_name")),
                    "formula_column": _clean_str(
                        arguments.get("formula_column")
                    ),
                    "formula_template": _clean_str(
                        arguments.get("formula_template")
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.rank":
        # Executor dispatches:
        #     sheet_rank(t, p.get("sheet_name", ""),
        #         p.get("rank_column", ""), output=p.get("output"))
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {
            "sheet_name": _clean_str(arguments.get("sheet_name")),
            "rank_column": _clean_str(arguments.get("rank_column")),
        }
        output = arguments.get("output")
        if isinstance(output, str) and output.strip():
            params["output"] = output
        return ActionPlan(
            operation="spreadsheet.rank",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.group_by":
        # Executor dispatches:
        #     sheet_group_by(t, p.get("sheet_name", ""),
        #         p.get("column", ""), agg_column=p.get("agg_column"),
        #         operation=p.get("operation", "count"))
        path = _clean_str(arguments.get("path"))
        params: Dict[str, Any] = {
            "sheet_name": _clean_str(arguments.get("sheet_name")),
            "column": _clean_str(arguments.get("column")),
        }
        agg = arguments.get("agg_column")
        if isinstance(agg, str) and agg.strip():
            params["agg_column"] = agg
        if "operation" in arguments:
            params["operation"] = str(arguments.get("operation") or "count")
        return ActionPlan(
            operation="spreadsheet.group_by",
            target=path or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.aggregate":
        # Executor dispatches:
        #     sheet_aggregate(t, p.get("sheet_name", ""),
        #         p.get("columns", []),
        #         operation=p.get("operation", "sum"))
        path = _clean_str(arguments.get("path"))
        columns = arguments.get("columns") or []
        if not isinstance(columns, list):
            columns = [str(columns)]
        return ActionPlan(
            operation="spreadsheet.aggregate",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet_name": _clean_str(arguments.get("sheet_name")),
                    "columns": [str(c) for c in columns],
                    "operation": str(
                        arguments.get("operation") or "sum"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.compare":
        # Executor dispatches:
        #     sheet_compare(t, p.get("sheet1", ""),
        #         p.get("other_path", ""), p.get("sheet2", ""))
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.compare",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet1": _clean_str(arguments.get("sheet1")),
                    "other_path": _clean_str(arguments.get("other_path")),
                    "sheet2": _clean_str(arguments.get("sheet2")),
                }
            ),
            confidence=1.0,
        )

    # --- browser.* (expansion; excluded trio omitted) ---

    if capability_id == "browser.open_url":
        url = _clean_str(arguments.get("url"))
        return ActionPlan(
            operation="browser.open_url",
            target=url or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "browser.search":
        # Executor dispatches:
        #     web_search(p.get("query", t), p.get("engine", "google"))
        # ``query`` goes into parameters; ``t`` falls back if no
        # query is supplied.
        query = _clean_str(arguments.get("query"))
        params: Dict[str, Any] = {
            "query": query,
        }
        engine = arguments.get("engine")
        if isinstance(engine, str) and engine.strip():
            params["engine"] = engine
        return ActionPlan(
            operation="browser.search",
            target=query or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "browser.extract":
        # Executor dispatches:
        #     browser_extract(p.get("selector"),
        #         p.get("session_id", "default"))
        # The selector is the natural primary identifier for the
        # element the action targets; we forward it as ``target``
        # so ``ActionPlan`` (which requires a target for ops not in
        # ``TARGETLESS_OPERATIONS``) validates.  ``browser.extract``
        # is intentionally NOT in ``TARGETLESS_OPERATIONS`` because
        # every extract call does have a real selector target.
        selector = _clean_str(arguments.get("selector"))
        return ActionPlan(
            operation="browser.extract",
            target=selector or None,
            parameters=_runtime_tokens(
                {
                    "selector": selector,
                    "session_id": _clean_str(
                        arguments.get("session_id") or "default"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.click":
        # Executor dispatches:
        #     browser_click(p.get("selector", t),
        #         p.get("session_id", "default"))
        #
        # The selector is the natural primary identifier for the
        # element the action targets.  ``browser.click`` is
        # non-destructive (no irreversible data mutation) and the
        # provider now emits a real ``element_found`` post-state
        # signal — verification_helpers verify_browser_click reads
        # it to derive ``verified=True`` when the element is still
        # present and interactable after the click.
        selector = _clean_str(arguments.get("selector"))
        return ActionPlan(
            operation="browser.click",
            target=selector or None,
            parameters=_runtime_tokens(
                {
                    "selector": selector,
                    "session_id": _clean_str(
                        arguments.get("session_id") or "default"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.find":
        # Executor dispatches:
        #     browser_find(p.get("text", t),
        #         p.get("session_id", "default"))
        text = _clean_str(arguments.get("text"))
        return ActionPlan(
            operation="browser.find",
            target=text or None,
            parameters=_runtime_tokens(
                {
                    "text": text,
                    "session_id": _clean_str(
                        arguments.get("session_id") or "default"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.get_title":
        # The browser session id is the natural primary target for
        # a session-scoped query like "what is the title of tab X
        # in session Y" - it identifies the live state the action
        # reads.  Forwarded as ``target`` so ``ActionPlan``
        # validates; the executor continues to read it from
        # ``plan.parameters["session_id"]`` as before.
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.get_title",
            target=session_id,
            parameters=_runtime_tokens(
                {
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.get_url":
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.get_url",
            target=session_id,
            parameters=_runtime_tokens(
                {
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.switch_tab":
        idx = arguments.get("index")
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.switch_tab",
            target=session_id,
            parameters=_runtime_tokens(
                {
                    "index": int(idx) if idx is not None else 0,
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.open_tab":
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.open_tab",
            target=session_id,
            parameters=_runtime_tokens(
                {
                    "url": _clean_str(arguments.get("url")) or None,
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.close_tab":
        idx = arguments.get("index")
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        params: Dict[str, Any] = {
            "session_id": session_id,
        }
        if idx is not None:
            params["index"] = int(idx)
        return ActionPlan(
            operation="browser.close_tab",
            target=session_id,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "browser.get_tabs":
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.get_tabs",
            target=session_id,
            parameters=_runtime_tokens(
                {
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.wait":
        # Executor dispatches:
        #     browser_wait(p.get("selector", t),
        #         float(p.get("timeout", 10.0)),
        #         p.get("session_id", "default"))
        selector = _clean_str(arguments.get("selector"))
        timeout = arguments.get("timeout", 10.0)
        try:
            timeout_f = float(timeout)
        except (TypeError, ValueError):
            timeout_f = 10.0
        return ActionPlan(
            operation="browser.wait",
            target=selector or None,
            parameters=_runtime_tokens(
                {
                    "selector": selector,
                    "timeout": timeout_f,
                    "session_id": _clean_str(
                        arguments.get("session_id") or "default"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.screenshot":
        # Executor dispatches:
        #     browser_screenshot(p.get("path"),
        #         p.get("session_id", "default"))
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="browser.screenshot",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "path": path,
                    "session_id": _clean_str(
                        arguments.get("session_id") or "default"
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.select":
        # Executor dispatches:
        #     browser_select(p.get("selector", t),
        #         value=p.get("value"), label=p.get("label"),
        #         index=int(p["index"]) if p.get("index") is not None
        #             else None,
        #         session_id=p.get("session_id", "default"))
        # The selector is the natural primary identifier for the
        # ``<select>`` element the action targets; forwarded as
        # ``target`` so ``ActionPlan`` validates (see also
        # ``browser.extract``).
        selector = _clean_str(arguments.get("selector"))
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        params: Dict[str, Any] = {
            "selector": selector,
            "session_id": session_id,
        }
        value = arguments.get("value")
        if isinstance(value, str) and value.strip():
            params["value"] = value
        label = arguments.get("label")
        if isinstance(label, str) and label.strip():
            params["label"] = label
        idx = arguments.get("index")
        if idx is not None:
            params["index"] = int(idx)
        return ActionPlan(
            operation="browser.select",
            target=selector or session_id,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "browser.download":
        # Executor dispatches:
        #     browser_download(p.get("url", t),
        #         save_path=p.get("save_path"),
        #         session_id=p.get("session_id", "default"))
        url = _clean_str(arguments.get("url"))
        params: Dict[str, Any] = {
            "url": url,
            "session_id": _clean_str(
                arguments.get("session_id") or "default"
            ),
        }
        save_path = arguments.get("save_path")
        if isinstance(save_path, str) and save_path.strip():
            params["save_path"] = save_path
        return ActionPlan(
            operation="browser.download",
            target=url or None,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    if capability_id == "browser.verify":
        # Executor dispatches:
        #     browser_verify(p.get("expected_url"),
        #         p.get("expected_title_contains"),
        #         p.get("session_id", "default"))
        # ``browser.verify`` reads the live page in the named
        # session, so the session id is the natural primary
        # target.  Forwarded as ``target`` so ``ActionPlan``
        # validates; the executor continues to read it from
        # ``plan.parameters["session_id"]`` as before.
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        params: Dict[str, Any] = {
            "session_id": session_id,
        }
        eu = arguments.get("expected_url")
        if isinstance(eu, str) and eu.strip():
            params["expected_url"] = eu
        etc = arguments.get("expected_title_contains")
        if isinstance(etc, str) and etc.strip():
            params["expected_title_contains"] = etc
        return ActionPlan(
            operation="browser.verify",
            target=session_id,
            parameters=_runtime_tokens(params),
            confidence=1.0,
        )

    # --- file.* (non-destructive) ---

    if capability_id == "file.copy":
        # Executor dispatches:
        #     copy_file(t, p.get("destination"), confirmed=True)
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.copy",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "destination": _clean_str(
                        arguments.get("destination")
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "file.move":
        # Executor dispatches:
        #     move_file(t, p.get("destination"), confirmed=True)
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.move",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "destination": _clean_str(
                        arguments.get("destination")
                    ),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "file.delete":
        # Executor dispatches:
        #     delete_file(t, confirmed=True)
        #
        # The adapter's ``_risk_tier_pre_check`` blocks this
        # operation BEFORE the executor is reached unless
        # ``confirmed=True`` is supplied, so by the time we
        # build a plan the human has explicitly approved the
        # deletion.  The adapter itself NEVER injects that
        # token (the ``TestDestructiveCapabilitiesRequireConfirmation``
        # suite pins the invariant).
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.delete",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "application.close":
        # Executor dispatches:
        #     close_application(t)
        #
        # The adapter's ``_risk_tier_pre_check`` only blocks
        # this operation when the unsaved-changes precondition
        # is active (i.e. the target application has a visible
        # top-level window with a title indicating unsaved
        # state).  When no such window is detected the
        # executor is allowed to run.
        application = _clean_str(arguments.get("application"))
        return ActionPlan(
            operation="application.close",
            target=application or None,
            application=application or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "cleanup.empty_recycle_bin":
        # Executor dispatches:
        #     empty_recycle_bin()
        #
        # The adapter's ``_risk_tier_pre_check`` blocks this
        # operation BEFORE the executor is reached unless
        # ``confirmed=True`` is supplied; this is a permanent,
        # irreversible action and the human MUST approve.
        #
        # The plan carries the literal sentinel
        # ``"<os_recycle_bin>"`` as ``target`` so the
        # ``ActionPlan`` Pydantic validator (which requires a
        # non-empty target for non-TARGETLESS ops) accepts the
        # plan.  The executor's ``_dispatch`` for this
        # operation (``action_executor.py:1338-1339``) does
        # NOT read ``t`` - it calls
        # ``os_manager.empty_recycle_bin()`` directly - so
        # the sentinel target value is never used to identify
        # a filesystem object.  It exists purely to satisfy
        # the plan-level target-required validator.
        return ActionPlan(
            operation="cleanup.empty_recycle_bin",
            target="<os_recycle_bin>",
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- application intelligence ---

    if capability_id == "application.inspect":
        application = _clean_str(arguments.get("application"))
        return ActionPlan(
            operation="application.inspect",
            target=application or None,
            application=application or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "application.list":
        return ActionPlan(
            operation="application.list",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- file intelligence (non-destructive) ---

    if capability_id == "file.inspect":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.inspect",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "file.read":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.read",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "file.search":
        path = _clean_str(arguments.get("path")) or "."
        query = _clean_str(arguments.get("query"))
        return ActionPlan(
            operation="file.search",
            target=query or None,
            parameters=_runtime_tokens(
                {"path": path, "query": query}
            ),
            confidence=1.0,
        )

    if capability_id == "file.hash":
        path = _clean_str(arguments.get("path"))
        algorithm = _clean_str(arguments.get("algorithm")) or "sha256"
        return ActionPlan(
            operation="file.hash",
            target=path or None,
            parameters=_runtime_tokens({"algorithm": algorithm}),
            confidence=1.0,
        )

    if capability_id == "file.open":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.open",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "file.create":
        path = _clean_str(arguments.get("path"))
        content = arguments.get("content", "")
        overwrite = bool(arguments.get("overwrite", False))
        return ActionPlan(
            operation="file.create",
            target=path or None,
            parameters=_runtime_tokens(
                {"content": content, "overwrite": overwrite}
            ),
            confidence=1.0,
        )

    # --- folder intelligence (non-destructive) ---

    if capability_id == "folder.inspect":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="folder.inspect",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "folder.open":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="folder.open",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "folder.create":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="folder.create",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- clipboard ---

    if capability_id == "clipboard.copy":
        text = arguments.get("text", "")
        return ActionPlan(
            operation="clipboard.copy",
            target=None,
            parameters=_runtime_tokens({"text": str(text)}),
            confidence=1.0,
        )

    if capability_id == "clipboard.paste":
        return ActionPlan(
            operation="clipboard.paste",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- notes ---

    if capability_id == "notes.create":
        text = arguments.get("text", "")
        return ActionPlan(
            operation="notes.create",
            target=None,
            parameters=_runtime_tokens({"text": str(text)}),
            confidence=1.0,
        )

    if capability_id == "notes.list":
        return ActionPlan(
            operation="notes.list",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- media ---

    if capability_id in ("media.play_pause", "media.next", "media.previous", "media.stop"):
        return ActionPlan(
            operation=capability_id,
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- volume ---

    if capability_id == "volume.up":
        steps = int(arguments.get("steps", 2))
        return ActionPlan(
            operation="volume.up",
            target=None,
            parameters=_runtime_tokens({"steps": steps}),
            confidence=1.0,
        )

    if capability_id == "volume.down":
        steps = int(arguments.get("steps", 2))
        return ActionPlan(
            operation="volume.down",
            target=None,
            parameters=_runtime_tokens({"steps": steps}),
            confidence=1.0,
        )

    if capability_id == "volume.mute_toggle":
        mute = arguments.get("mute")
        return ActionPlan(
            operation="volume.mute_toggle",
            target=None,
            parameters=_runtime_tokens(
                {"mute": None if mute is None else bool(mute)}
            ),
            confidence=1.0,
        )

    if capability_id == "volume.set":
        percent = _clean_str(arguments.get("percent"))
        return ActionPlan(
            operation="volume.set",
            target=percent or None,
            parameters=_runtime_tokens({"percent": percent}),
            confidence=1.0,
        )

    if capability_id == "volume.get":
        return ActionPlan(
            operation="volume.get",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- display ---

    if capability_id == "display.brightness_set":
        percent = arguments.get("percent")
        direction = arguments.get("direction")
        return ActionPlan(
            operation="display.brightness_set",
            target=None,
            parameters=_runtime_tokens(
                {"percent": percent, "direction": direction}
            ),
            confidence=1.0,
        )

    if capability_id == "display.brightness_get":
        return ActionPlan(
            operation="display.brightness_get",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- hardware ---

    if capability_id == "hardware.battery":
        return ActionPlan(
            operation="hardware.battery",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "hardware.stats":
        return ActionPlan(
            operation="hardware.stats",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "hardware.storage":
        return ActionPlan(
            operation="hardware.storage",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- system / network ---

    if capability_id == "system.status":
        return ActionPlan(
            operation="system.status",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "system.open_settings":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="system.open_settings",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "network.list_wifi":
        return ActionPlan(
            operation="network.list_wifi",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- process ---

    if capability_id == "process.list":
        target = _clean_str(arguments.get("target"))
        limit = int(arguments.get("limit", 500))
        return ActionPlan(
            operation="process.list",
            target=target or None,
            parameters=_runtime_tokens({"limit": limit}),
            confidence=1.0,
        )

    if capability_id == "process.inspect":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="process.inspect",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- screen ---

    if capability_id == "screen.capture":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="screen.capture",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- web / daily ---

    if capability_id == "web.research":
        query = _clean_str(arguments.get("query"))
        max_results = int(arguments.get("max_results", 5))
        return ActionPlan(
            operation="web.research",
            target=query or None,
            parameters=_runtime_tokens({"max_results": max_results}),
            confidence=1.0,
        )

    if capability_id == "web.weather":
        city = _clean_str(arguments.get("city"))
        return ActionPlan(
            operation="web.weather",
            target=city or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "time.world_clock":
        city = _clean_str(arguments.get("city"))
        return ActionPlan(
            operation="time.world_clock",
            target=city or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- math ---

    if capability_id == "math.evaluate":
        expression = _clean_str(arguments.get("expression"))
        return ActionPlan(
            operation="math.evaluate",
            target=expression or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- window management ---

    if capability_id in ("window.minimize_all", "window.restore", "window.show_desktop"):
        return ActionPlan(
            operation=capability_id,
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- browser extras ---

    if capability_id == "browser.scroll":
        direction = _clean_str(arguments.get("direction")) or "down"
        amount = int(arguments.get("amount", 3))
        session_id = _clean_str(
            arguments.get("session_id") or "default"
        )
        return ActionPlan(
            operation="browser.scroll",
            target=direction,
            parameters=_runtime_tokens(
                {
                    "direction": direction,
                    "amount": amount,
                    "session_id": session_id,
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.capabilities":
        return ActionPlan(
            operation="browser.capabilities",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- GUI extras ---

    if capability_id == "gui.focus_window":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="gui.focus_window",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.inspect_window":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="gui.inspect_window",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.click":
        x = int(arguments.get("x", 0))
        y = int(arguments.get("y", 0))
        return ActionPlan(
            operation="gui.click",
            target=None,
            parameters=_runtime_tokens({"x": x, "y": y}),
            confidence=1.0,
        )

    if capability_id == "gui.read_visible_text":
        return ActionPlan(
            operation="gui.read_visible_text",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.select":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="gui.select",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.scroll":
        direction = _clean_str(arguments.get("direction")) or "down"
        amount = int(arguments.get("amount", 3))
        return ActionPlan(
            operation="gui.scroll",
            target=None,
            parameters=_runtime_tokens(
                {"direction": direction, "amount": amount}
            ),
            confidence=1.0,
        )

    if capability_id == "gui.keyboard_action":
        key = _clean_str(arguments.get("key"))
        return ActionPlan(
            operation="gui.keyboard_action",
            target=None,
            parameters=_runtime_tokens({"key": key}),
            confidence=1.0,
        )

    # --- data ---

    if capability_id == "data.inspect":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="data.inspect",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "data.transform":
        source = _clean_str(arguments.get("source"))
        target_format = _clean_str(arguments.get("target_format"))
        output = _clean_str(arguments.get("output"))
        return ActionPlan(
            operation="data.transform",
            target=source or None,
            parameters=_runtime_tokens(
                {"target_format": target_format, "output": output}
            ),
            confidence=1.0,
        )

    # --- document create variants ---

    if capability_id in ("document.create_csv", "document.create_json", "document.create_markdown"):
        path = _clean_str(arguments.get("path"))
        content = arguments.get("content", "")
        return ActionPlan(
            operation=capability_id,
            target=path or None,
            parameters=_runtime_tokens({"content": content}),
            confidence=1.0,
        )

    if capability_id == "document.inspect_intel":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.inspect_intel",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- cleanup read-only ---

    if capability_id == "cleanup.recycle_bin_query":
        return ActionPlan(
            operation="cleanup.recycle_bin_query",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    # --- package read-only ---

    if capability_id == "package.search":
        query = _clean_str(arguments.get("query"))
        max_results = int(arguments.get("max_results", 5))
        return ActionPlan(
            operation="package.search",
            target=query or None,
            parameters=_runtime_tokens({"max_results": max_results}),
            confidence=1.0,
        )

    if capability_id == "application.window_list":
        return ActionPlan(
            operation="application.window_list",
            target="windows",
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "browser.get_page_state":
        return ActionPlan(
            operation="browser.get_page_state",
            target=None,
            parameters=_runtime_tokens(
                {"session_id": _clean_str(arguments.get("session_id") or "default")}
            ),
            confidence=1.0,
        )

    if capability_id == "browser.type":
        selector = _clean_str(arguments.get("selector"))
        return ActionPlan(
            operation="browser.type",
            target=selector or None,
            parameters=_runtime_tokens(
                {
                    "text": str(arguments.get("text") or ""),
                    "session_id": _clean_str(arguments.get("session_id") or "default"),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "browser.upload":
        selector = _clean_str(arguments.get("selector"))
        return ActionPlan(
            operation="browser.upload",
            target=selector or None,
            parameters=_runtime_tokens(
                {
                    "file_path": _clean_str(arguments.get("file_path")),
                    "session_id": _clean_str(arguments.get("session_id") or "default"),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "document.inspect":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="document.inspect",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "file.watch":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="file.watch",
            target=path or None,
            parameters=_runtime_tokens(
                {"event": _clean_str(arguments.get("event") or "modified")}
            ),
            confidence=1.0,
        )

    if capability_id == "gui.double_click":
        return ActionPlan(
            operation="gui.double_click",
            target="screen",
            parameters=_runtime_tokens(
                {
                    "x": int(arguments.get("x", 0)),
                    "y": int(arguments.get("y", 0)),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "gui.drag":
        return ActionPlan(
            operation="gui.drag",
            target="screen",
            parameters=_runtime_tokens(
                {
                    "start_x": int(arguments.get("start_x", 0)),
                    "start_y": int(arguments.get("start_y", 0)),
                    "end_x": int(arguments.get("end_x", 0)),
                    "end_y": int(arguments.get("end_y", 0)),
                    "duration": float(arguments.get("duration", 0.5)),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "gui.hotkey":
        return ActionPlan(
            operation="gui.hotkey",
            target="screen",
            parameters=_runtime_tokens(
                {"keys": _clean_str(arguments.get("keys"))}
            ),
            confidence=1.0,
        )

    if capability_id == "gui.inspect_ui_tree":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="gui.inspect_ui_tree",
            target=target or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "gui.wait":
        return ActionPlan(
            operation="gui.wait",
            target="screen",
            parameters=_runtime_tokens(
                {"seconds": float(arguments.get("seconds", 1.0))}
            ),
            confidence=1.0,
        )

    if capability_id == "gui.wait_for_state":
        return ActionPlan(
            operation="gui.wait_for_state",
            target="screen",
            parameters=_runtime_tokens(
                {
                    "condition": _clean_str(arguments.get("condition")),
                    "timeout": float(arguments.get("timeout", 3.0)),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "gui.wait_for_window":
        target = _clean_str(arguments.get("target"))
        return ActionPlan(
            operation="gui.wait_for_window",
            target=target or None,
            parameters=_runtime_tokens(
                {
                    "timeout": float(arguments.get("timeout", 3.0)),
                    "poll_interval": float(arguments.get("poll_interval", 0.2)),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.add_column":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.add_column",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet_name": _clean_str(arguments.get("sheet_name")),
                    "column_name": _clean_str(
                        arguments.get("column_name") or arguments.get("column")
                    ),
                    "values": list(arguments.get("values") or []),
                    "output": _clean_str(arguments.get("output")),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.create_from_dicts":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.create_from_dicts",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "data": list(arguments.get("data") or []),
                    "sheet_name": _clean_str(arguments.get("sheet_name") or "Sheet1"),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "spreadsheet.update_cell":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="spreadsheet.update_cell",
            target=path or None,
            parameters=_runtime_tokens(
                {
                    "sheet_name": _clean_str(arguments.get("sheet_name")),
                    "row": int(arguments.get("row", 0)),
                    "column": _clean_str(arguments.get("column")),
                    "value": arguments.get("value"),
                    "output": _clean_str(arguments.get("output")),
                }
            ),
            confidence=1.0,
        )

    if capability_id == "weather.current":
        city = _clean_str(arguments.get("city"))
        return ActionPlan(
            operation="weather.current",
            target=city or None,
            parameters=_runtime_tokens({"city": city}),
            confidence=1.0,
        )

    # --- destructive / gated ---

    if capability_id == "file.rename":
        path = _clean_str(arguments.get("path"))
        new_name = _clean_str(arguments.get("new_name"))
        return ActionPlan(
            operation="file.rename",
            target=path or None,
            parameters=_runtime_tokens({"new_name": new_name}),
            confidence=1.0,
        )

    if capability_id == "folder.rename":
        path = _clean_str(arguments.get("path"))
        new_name = _clean_str(arguments.get("new_name"))
        return ActionPlan(
            operation="folder.rename",
            target=path or None,
            parameters=_runtime_tokens({"new_name": new_name}),
            confidence=1.0,
        )

    if capability_id == "folder.move":
        path = _clean_str(arguments.get("path"))
        destination = _clean_str(arguments.get("destination"))
        return ActionPlan(
            operation="folder.move",
            target=path or None,
            parameters=_runtime_tokens({"destination": destination}),
            confidence=1.0,
        )

    if capability_id == "folder.delete":
        path = _clean_str(arguments.get("path"))
        return ActionPlan(
            operation="folder.delete",
            target=path or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "folder.organize":
        path = _clean_str(arguments.get("path"))
        dry_run = bool(arguments.get("dry_run", False))
        return ActionPlan(
            operation="folder.organize",
            target=path or None,
            parameters=_runtime_tokens({"dry_run": dry_run}),
            confidence=1.0,
        )

    if capability_id == "document.create_docx":
        path = _clean_str(arguments.get("path"))
        title = _clean_str(arguments.get("title")) or "Genesis Document"
        sections = arguments.get("sections", [])
        return ActionPlan(
            operation="document.create_docx",
            target=path or None,
            parameters=_runtime_tokens(
                {"title": title, "sections": sections}
            ),
            confidence=1.0,
        )

    if capability_id == "document.create_pdf":
        path = _clean_str(arguments.get("path"))
        title = _clean_str(arguments.get("title")) or "Untitled"
        content = arguments.get("content", "")
        return ActionPlan(
            operation="document.create_pdf",
            target=path or None,
            parameters=_runtime_tokens(
                {"title": title, "content": content}
            ),
            confidence=1.0,
        )

    if capability_id == "package.install":
        package = _clean_str(arguments.get("package"))
        return ActionPlan(
            operation="package.install",
            target=package or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "package.uninstall":
        package = _clean_str(arguments.get("package"))
        return ActionPlan(
            operation="package.uninstall",
            target=package or None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    if capability_id == "network.connect_wifi":
        ssid = _clean_str(arguments.get("ssid"))
        password = _clean_str(arguments.get("password"))
        return ActionPlan(
            operation="network.connect_wifi",
            target=ssid or None,
            parameters=_runtime_tokens({"password": password}),
            confidence=1.0,
        )

    if capability_id == "workstation.lock":
        return ActionPlan(
            operation="workstation.lock",
            target=None,
            parameters=_runtime_tokens({}),
            confidence=1.0,
        )

    raise ValueError(
        f"agent_framework_adapter: unsupported capability_id "
        f"{capability_id!r}"
    )


def _build_tool_description(
    descriptor: CapabilityDescriptor,
    tool_name: Optional[str] = None,
) -> str:
    """
    Build a meaningful, descriptor-derived description for the
    Agent Framework tool.  NOT a generic placeholder.

    Pulls the actual fields present on the descriptor (description,
    category, supported_inputs, permissions, provider, risk_level)
    - does NOT invent anything.  If a field is empty in the
    descriptor it is simply omitted from the rendered text.

    ``tool_name`` is the public-facing ID the model sees (for
    example ``document.create``); the leading prefix uses the
    tool name so the description matches the tool the model is
    reading about, while the underlying descriptor fields still
    drive every other sentence.
    """

    bits: List[str] = []

    bits.append(f"Genesis capability: {tool_name or descriptor.capability_id}.")

    bits.append(descriptor.description.strip())

    category_value = getattr(
        descriptor.category,
        "value",
        str(descriptor.category),
    )

    if descriptor.supported_inputs:
        bits.append(
            "Accepts: " + ", ".join(sorted(descriptor.supported_inputs))
        )

    if descriptor.provider:
        bits.append(f"Provider: {descriptor.provider}.")

    risk_level = str(
        getattr(descriptor, "risk_level", "") or "low"
    )
    bits.append(f"Risk level: {risk_level}.")

    if descriptor.permissions:
        bits.append(
            "Required permissions: "
            + ", ".join(sorted(descriptor.permissions))
        )

    postconditions = [
        str(item)
        for item in (getattr(descriptor, "postconditions", ()) or ())
        if str(item).strip()
    ]
    if postconditions:
        bits.append(
            "Observable postconditions: "
            + "; ".join(postconditions)
        )

    declared_side_effects = [
        str(item)
        for item in (getattr(descriptor, "side_effects", ()) or ())
        if str(item).strip()
    ]
    if declared_side_effects:
        side_effect_text = "; ".join(declared_side_effects)
    elif tool_name in ALWAYS_DESTRUCTIVE:
        side_effect_text = "destructive mutation (always_destructive tier)"
    elif tool_name in CONDITIONALLY_DESTRUCTIVE:
        side_effect_text = (
            "conditional mutation (conditionally_destructive tier)"
        )
    elif risk_level.lower() in {"medium", "high", "critical"}:
        side_effect_text = f"mutating capability (risk level: {risk_level})"
    else:
        side_effect_text = (
            f"read-only or non-destructive (risk level: {risk_level})"
        )
    bits.append(f"Side effects: {side_effect_text}.")

    bits.append(
        f"Category: {category_value}. Result carries a real "
        "verified/verification_reason envelope sourced from "
        "Genesis's ActionExecutor, including status, execution, "
        "verification, and metadata.evidence_contract - a "
        "'verified=true' result means the post-state was actually "
        "observed, not just that the provider reported success."
    )

    return " ".join(bits)


# ============================================================
# ADAPTER
# ============================================================


class AgentFrameworkAdapter:
    """
    Adapter that registers a fixed subset of Genesis capabilities
    as Microsoft Agent Framework function tools, and routes every
    invocation through the existing ActionExecutor.

    The adapter holds a reference to a real ActionExecutor; it does
    not construct one internally because OSManager construction is
    expensive and may be application-scoped in the calling code.
    """

    def __init__(
        self,
        executor: ActionExecutor,
        *,
        capability_ids: Sequence[str] = POC_CAPABILITIES,
    ) -> None:
        if executor is None:
            raise ValueError(
                "AgentFrameworkAdapter requires an ActionExecutor."
            )
        self.executor = executor
        self.capability_ids: Tuple[str, ...] = tuple(capability_ids)

    # ----------------------------------------------------
    # Capability metadata -> tool description
    # ----------------------------------------------------

    def describe_capability(
        self,
        capability_id: str,
    ) -> CapabilityDescriptor:
        """
        Resolve and return the registered CapabilityDescriptor
        for a capability ID.  Raises ``CapabilityNotFoundError``
        (from CapabilityRegistry) when the ID is unknown.

        ``document.create`` is the canonical public alias used in
        the UCCL roadmap but is not itself registered - the
        registry ships concrete capabilities (``document.create_txt``,
        ``document.create_docx``, ``document.create_csv``,
        ``document.create_json``, ``document.create_markdown``).
        ``document.create`` is resolved to ``document.create_txt``,
        the most generic format-agnostic sibling, so the
        descriptor-derived description is meaningful without
        modifying the registry.

        ``document.search`` is wired through the executor's
        dispatch table but is not itself registered - the
        registry lists it under ``document.search_intel``. The
        adapter aliases the user-facing name to the
        ``_intel`` form so the descriptor still flows from
        the registry.
        """

        if capability_id == "document.create":
            return CapabilityRegistry.get("document.create_txt")
        if capability_id == "document.search":
            return CapabilityRegistry.get("document.search_intel")
        return CapabilityRegistry.get(capability_id)

    # ----------------------------------------------------
    # ActionPlan + result helpers
    # ----------------------------------------------------

    def build_plan(
        self,
        capability_id: str,
        arguments: Mapping[str, Any],
        consumed_approval: Optional[Dict[str, Any]] = None,
    ) -> ActionPlan:
        """
        Translate tool-call arguments into an ActionPlan.  Pure
        function - does not touch the executor.

        ``consumed_approval`` is the record produced by consuming THIS
        request's own approval token. It is threaded through to
        ``_build_action_plan`` so the grant is derived from this
        request only.
        """

        plan = _build_action_plan(
            capability_id, arguments, consumed_approval
        )

        # Record which registered capability this plan invokes. The
        # adapter knows this from its own routing; the executor only
        # sees the bare operation verb, which is ambiguous for browser
        # capabilities. Advisory for gating only -- the resolver takes
        # the most restrictive of capability_id and operation.
        try:
            if getattr(plan, "capability_id", None) is None:
                plan = plan.model_copy(
                    update={"capability_id": capability_id}
                )
        except Exception:
            pass

        # Move the trusted grant out of the parameter dict and onto the
        # plan's dedicated channel. The grant must never travel inside
        # `parameters`: that dict is model-visible and serialized, and
        # the whole point of the channel is that authorization does not
        # ride there.
        grant = (plan.parameters or {}).pop("_authorization_grant", None)
        if grant is not None:
            try:
                from .action_plan import attach_authorization

                plan = attach_authorization(
                    plan,
                    grant,
                    arguments={
                        key: value
                        for key, value in arguments.items()
                        if key != "approval_token"
                    },
                )
            except Exception:
                # Fail closed: no grant attached means the executor
                # blocks this Tier 1 plan.
                pass
        return plan

    def execute_plan(
        self,
        plan: ActionPlan,
        *,
        _approval_prechecked: bool = False,
    ) -> ActionResult:
        """
        Route an ActionPlan through the EXISTING ActionExecutor.
        The executor is the single source of truth for validation,
        safety, confirmation, dispatch, verification, and
        normalization; this method simply forwards.

        ``execute_capability`` (the adapter entry point used by
        Agent Framework tools) wraps this with
        ``_risk_tier_pre_check`` so destructive capabilities
        pause for an explicit human approval token before
        ``executor.execute`` is called.
        """

        if not _approval_prechecked:
            arguments = dict(plan.parameters or {})
            if plan.target is not None:
                arguments.setdefault("target", plan.target)
                arguments.setdefault("path", plan.target)
            if plan.application:
                arguments.setdefault("application", plan.application)
            pre_check = self._risk_tier_pre_check(
                plan.operation,
                arguments,
                approval_token=arguments.get("approval_token"),
            )
            if pre_check is not None:
                return pre_check
        return self.executor.execute(plan)

    # ----------------------------------------------------
    # Risk-tier pre-check (destructive capabilities)
    # ----------------------------------------------------
    #
    # The confirmation gate inside ``ActionExecutor.execute``
    # (``action_executor.py:482-511``) already blocks destructive
    # operations when the caller has not supplied
    # ``confirmed=True``.  That is the safety property.  The
    # pre-check below adds a second property on top: it makes the
    # confirmation request **visibly distinct from a normal
    # failure** to the model.  The model receives a structured
    # ``ActionResult`` with:
    #
    #     status="confirmation_required"
    #     metadata.confirmation_required = True
    #     metadata.confirmation_message = "<plain language>"
    #     metadata.adapter_risk_tier = "always_destructive"
    #                                     | "conditionally_destructive"
    #                                     | "safe"
    #     success=False, executed=False, verified=False
    #
    # so it can present the proposal to the user and re-invoke
    # the same tool with ``confirmed=True`` once approval is
    # granted.  The adapter itself NEVER injects that token
    # (the ``TestDestructiveCapabilitiesRequireConfirmation``
    # suite pins the invariant).

    def _risk_tier_pre_check(
        self,
        capability_id: str,
        arguments: Mapping[str, Any],
        approval_token: Optional[str] = None,
        consumed_out: Optional[Dict[str, Any]] = None,
    ) -> Optional[ActionResult]:
        """
        Return a structured ``confirmation_required``
        ``ActionResult`` if the call would execute a destructive
        capability without a real approval token.  Return
        ``None`` when the call is safe to forward to the
        executor.

        ``consumed_out`` is an optional dict the caller supplies to
        RECEIVE the ApprovalStore record this call just consumed. That
        record must reach the plan builder so the grant is minted from
        this request's own approval. It is passed out explicitly because
        the previous mechanism -- a module global -- was readable by any
        other in-flight request.

        Explicit human-approval token gate (high/critical risk):
        for capabilities in ``APPROVAL_REQUIRED_CAPABILITIES``
        (file.delete, folder.delete, cleanup.empty_recycle_bin,
        package.uninstall, package.install, application.close)
        the caller MUST supply ``approval_token`` with format
        ``HUMAN-APPROVE:<capability_id>:<nonce>`` (nonce >= 4
        chars).  The token may be passed as the explicit
        ``approval_token`` kwarg or as
        ``arguments["approval_token"]``.  If missing/invalid the
        adapter returns ``success=False``,
        ``status="confirmation_required"``,
        ``metadata["confirmation_required"]=True``,
        ``executed=False, verified=False`` and does NOT call the
        executor.  ``confirmed=True`` alone is NOT sufficient for
        these high/critical capabilities.
        """

        effective_token = _extract_approval_token(
            arguments, approval_token
        )

        # --- Explicit approval-token gate (high/critical) ---
        # Unconditional for irreversible ops; conditional for
        # application.close (only when the unsaved-changes
        # precondition is active — safe/transient closes still
        # flow through so closing Calculator never prompts).
        if requires_approval_token(capability_id, arguments):
            needs_token = True
            precondition_reason = ""
            if capability_id == "application.close":
                active, reason = (
                    self._check_unsaved_changes_precondition(
                        capability_id=capability_id,
                        arguments=arguments,
                    )
                )
                needs_token = active
                precondition_reason = reason
            if needs_token:
                consumed = _consume_approval_token(
                    effective_token,
                    capability_id,
                    arguments,
                )
                if consumed is None:
                    if capability_id == "application.close":
                        msg = (
                            f"This tool call proposes to perform "
                            f"``{capability_id}`` on a target that "
                            f"appears to have unsaved state "
                            f"({precondition_reason}).  High-risk "
                            f"close requires an explicit human-approval "
                            f"token.  Re-invoke the same tool with "
                            f"``approval_token='HUMAN-APPROVE:"
                            f"{capability_id}:<nonce>'`` (nonce >= 4 "
                            f"chars, e.g. 'HUMAN-APPROVE:"
                            f"{capability_id}:7f3a') only after the "
                            f"user has explicitly approved.  "
                            f"``confirmed=True`` alone is not "
                            f"sufficient.  The action was NOT executed "
                            f"(success=False, executed=False, "
                            f"verified=False)."
                        )
                    else:
                        msg = (
                            f"This tool call proposes to perform the "
                            f"destructive operation "
                            f"``{capability_id}``.  High/critical-risk "
                            f"operations require an explicit human-approval "
                            f"token.  Re-invoke the same tool with "
                            f"``approval_token='HUMAN-APPROVE:"
                            f"{capability_id}:<nonce>'`` (nonce >= 4 "
                            f"chars, e.g. 'HUMAN-APPROVE:"
                            f"{capability_id}:7f3a') only after the "
                            f"user has explicitly approved.  "
                            f"``confirmed=True`` alone is not "
                            f"sufficient.  The action was NOT executed "
                            f"(success=False, executed=False, "
                            f"verified=False)."
                        )
                    return self._build_confirmation_required_result(
                        capability_id=capability_id,
                        arguments=arguments,
                        risk_tier=(
                            "conditionally_destructive"
                            if capability_id == "application.close"
                            else "always_destructive"
                        ),
                        confirmation_message=msg,
                    )
                # Valid token — allow through to the executor.
                # (The plan builder promotes it to confirmed=True
                # for the executor's own gate.)
                # For application.close with an active precondition
                # we are done; for the unconditional set we are
                # done too.  Fall through to return None.
                #
                # Hand the consumed record to the caller so the grant is
                # minted from THIS request's approval. It travels with
                # the call rather than through shared module state.
                if consumed_out is not None:
                    consumed_out["consumed_approval"] = consumed
                if capability_id == "application.close":
                    return None
                return None

        # NOTE (2026-10-15): the previous early return here was
        #
        #     if bool(arguments.get("confirmed", False)):
        #         return None
        #
        # which let a CALLER-SUPPLIED `confirmed` skip the
        # ALWAYS_DESTRUCTIVE and CONDITIONALLY_DESTRUCTIVE checks below.
        # `arguments` is model-controlled tool-call JSON, so a model
        # could set `confirmed: true` and unlock its own destructive
        # operation with no human involved. Approval authority now comes
        # ONLY from a validated approval token (see `requires_approval_token`
        # above) and the AuthorizationGrant it mints.

        if capability_id in ALWAYS_DESTRUCTIVE:
            return self._build_confirmation_required_result(
                capability_id=capability_id,
                arguments=arguments,
                risk_tier="always_destructive",
                confirmation_message=(
                    f"This tool call proposes to perform the "
                    f"destructive operation "
                    f"``{capability_id}`` on the computer or "
                    f"its data.  The action is irreversible from "
                    f"the user's perspective and requires "
                    f"explicit human approval before the "
                    f"executor is allowed to dispatch it.  "
                    f"Re-invoke the same tool with "
                    f"``confirmed=True`` plus "
                    f"``approval_token='HUMAN-APPROVE:"
                    f"{capability_id}:<nonce>'`` only after the user "
                    f"has explicitly approved the proposal."
                ),
            )

        if capability_id in CONDITIONALLY_DESTRUCTIVE:
            precondition_active, reason = (
                self._check_unsaved_changes_precondition(
                    capability_id=capability_id,
                    arguments=arguments,
                )
            )
            if precondition_active:
                return self._build_confirmation_required_result(
                    capability_id=capability_id,
                    arguments=arguments,
                    risk_tier="conditionally_destructive",
                    confirmation_message=(
                        f"This tool call proposes to perform "
                        f"``{capability_id}`` on a target that "
                        f"appears to have unsaved state.  The "
                        f"precondition that triggered the gate "
                        f"is: {reason}.  Forced close in this "
                        f"state can drop the user's work.  "
                        f"Re-invoke the same tool with "
                        f"``confirmed=True`` plus "
                        f"``approval_token='HUMAN-APPROVE:"
                        f"{capability_id}:<nonce>'`` only after the "
                        f"user has explicitly approved the "
                        f"close."
                    ),
                )
            # Precondition is INACTIVE - the close is a normal,
            # reversible no-op from the user's perspective.
            # Let the call through to the executor.
            return None

        # Not in either risk tier - safe to forward.
        return None

    def _build_confirmation_required_result(
        self,
        *,
        capability_id: str,
        arguments: Mapping[str, Any],
        risk_tier: str,
        confirmation_message: str,
    ) -> ActionResult:
        """
        Build the structured ``confirmation_required``
        ``ActionResult`` the adapter returns to the model when
        a destructive capability is invoked without
        ``confirmed=True``.  This result is clearly distinct
        from a normal failure envelope so the model can
        present the proposal to the user, obtain approval, and
        re-invoke the same tool with ``confirmed=True``.
        """

        target = (
            str(arguments.get("path"))
            or str(arguments.get("application"))
            or str(arguments.get("destination"))
            or ""
        ).strip() or None

        metadata: Dict[str, Any] = {
            "executor_version": ActionExecutor.VERSION,
            "execution_contract": ActionExecutor.EXECUTION_CONTRACT,
            "execution_stage": "adapter_risk_tier_pre_check",
            "confirmation_required": True,
            "confirmation_message": confirmation_message,
            "adapter_risk_tier": risk_tier,
            "adapter_pre_check": "AgentFrameworkAdapter._risk_tier_pre_check",
        }

        # HIL approval queue (Phase 2/13 groundwork, honest
        # programmatic HIL): every confirmation_required bounce
        # auto-creates a traceable pending request so a human UI
        # (or test harness) can approve it out-of-band.
        #
        # Item 9C: the queue still happens, but its `approval_id` is NO
        # LONGER placed in the model-facing metadata. This result is
        # handed straight back to the model, so anything in `metadata`
        # is a handle the model can read and echo.
        #
        # Measured before removing it: the exposure was NOT exploitable.
        # A token fabricated from the pending id
        # (`HUMAN-APPROVE:file.delete:<approval_id>`) and a nonce
        # invented outright both passed `is_valid_approval_token` --
        # which is a pure FORMAT check -- but both were then refused by
        # ApprovalStore.consume_token, because the record is `pending`,
        # not `approved`, and an invented nonce matches no record at
        # all. So this is hardening, not a live bypass fix.
        #
        # It still had to go. A handle that confers no authority today
        # is one refactor away from conferring some, and per Item 9A the
        # only real route to authority is now the human-approval
        # channel, which mints from a human's typed decision and does
        # not read this id at all. Handing the model a queue ticket
        # invites exactly the "re-invoke with the token I was given"
        # pattern the message above describes, when no such token can
        # be obtained this way.
        try:
            from .approval_store import ApprovalStore

            try:
                args_snapshot = dict(arguments)
            except Exception:
                args_snapshot = {}
            ApprovalStore.get_default().request(
                capability_id, args_snapshot
            )
        except Exception:
            pass

        return ActionResult.failure_result(
            operation=capability_id,
            target=target,
            application=(
                str(arguments.get("application")).strip()
                if isinstance(arguments.get("application"), str)
                and str(arguments.get("application")).strip()
                else None
            ),
            message=confirmation_message,
            status="confirmation_required",
            error=confirmation_message,
            executed=False,
            verified=False,
            plan=None,
            metadata=metadata,
        )

    def _check_unsaved_changes_precondition(
        self,
        *,
        capability_id: str,
        arguments: Mapping[str, Any],
    ) -> Tuple[bool, str]:
        """
        Evaluate whether the destructive precondition for
        ``capability_id`` is currently active.  Today the only
        conditional capability is ``application.close``; the
        precondition is "the target application has unsaved
        user state visible in any of its top-level windows".

        Returns ``(active, reason)``.  When ``active`` is
        ``True`` the adapter pauses for confirmation; when it
        is ``False`` the executor is allowed to run.

        The check is Windows-specific (uses user32
        ``EnumWindows`` + ``GetWindowTextW``).  On non-Windows
        platforms or when user32 is unavailable the check
        returns ``(False, "platform not supported")`` so the
        call is allowed to proceed.

        CORRECTION (Item 10B, S11). This used to assert that these
        false negatives are rescued further down the executor path by an
        execution-safety backstop. THAT WAS FALSE.
        ``ExecutionSafety.check()`` is a deny-list plus a
        capability lookup; it never inspects windows, documents
        or unsaved state, so there is no downstream safety net and a
        false negative here is a false negative full stop. The trade-off
        is deliberate and is the one 7B drew the line at: a MISSING
        platform capability stays quiet, while a REGISTERED detector
        that RAISES now escalates, because a check that failed is not a
        verdict of "nothing unsaved".

        AUTHORITY (ledger item, F5 classification): this method no
        longer decides anything on its own. It delegates to
        ``genesis_os.blast_radius``, which owns the decision, and the
        platform-specific detection below is registered there as a
        detector. The tier and the precondition gate therefore cannot
        drift apart -- previously the escalation existed only here, so a
        blast-radius-only enforcement layer would have treated
        ``application.close`` as ungated and silently allowed
        unsaved-work loss.
        """

        if capability_id != "application.close":
            # No other conditional capabilities yet.
            return (False, "no precondition defined")

        from .blast_radius import (
            BlastRadius,
            register_unsaved_changes_detector,
            resolve_blast_radius,
        )

        # Single registration point for the platform detection.
        register_unsaved_changes_detector(
            "application.close",
            self._has_unsaved_windows_for_application_close,
        )

        resolved = resolve_blast_radius(
            capability_id, arguments, context=None
        )
        active = resolved is BlastRadius.IRREVERSIBLE_OR_OUTWARD
        reason = (
            self._has_unsaved_windows_for_application_close(arguments)[1]
            if active
            else "no unsaved state observed"
        )
        return (active, reason)

    def _has_unsaved_windows_for_application_close(
        self,
        arguments: Mapping[str, Any],
    ) -> Tuple[bool, str]:
        """
        Windows user32-based check: enumerate the top-level
        windows, look for the resolved application process, and
        scan their titles for the unsaved-changes patterns
        declared in ``UNSAVED_TITLE_PATTERNS``.

        This is a best-effort, observable signal.  The same
        heuristic is documented at the top of the file: false
        positives cost a confirmation prompt the user can
        skip; false negatives risk silent data loss, so the
        heuristic errs on the conservative side.
        """

        application_arg = arguments.get("application")
        if not (
            isinstance(application_arg, str)
            and application_arg.strip()
        ):
            # Without a target application name we cannot
            # evaluate the precondition safely.  Fall back
            # to the executor (which will produce a clear
            # "could not resolve" failure for the model to
            # react to).
            return (False, "no application target supplied")

        target_name = application_arg.strip().lower()
        if any(
            hint in target_name
            for hint in TRANSIENT_PROCESS_HINTS
        ):
            return (False, "transient / no-save-state process")

        # Lazy import of user32 so non-Windows test
        # environments can still load this module.
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception:
            return (False, "user32 unavailable on this platform")

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        matches: List[str] = []

        def _callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                # Open the process briefly to read its
                # executable name; QueryFullProcessImageNameW
                # is available on Vista+ (which we assume on
                # all supported test machines).
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h_process = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                    PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid.value,
                )
                if not h_process:
                    return True
                try:
                    buf = ctypes.create_unicode_buffer(512)
                    size = wintypes.DWORD(512)
                    ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(  # type: ignore[attr-defined]
                        h_process, 0, buf, ctypes.byref(size)
                    )
                    if not ok:
                        return True
                    exe_name = buf.value.split("\\")[-1].lower()
                finally:
                    ctypes.windll.kernel32.CloseHandle(h_process)  # type: ignore[attr-defined]
                if target_name not in exe_name and exe_name not in target_name:
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                title_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(
                    hwnd, title_buf, length + 1
                )
                title = (title_buf.value or "").strip()
                if not title:
                    return True
                for pat in UNSAVED_TITLE_PATTERNS:
                    if pat.lower() in title.lower():
                        matches.append(
                            f"{exe_name}: {title!r} matches "
                            f"{pat!r}"
                        )
                        return True
            except Exception:
                # Defensive: any per-window failure must
                # NOT block the whole enumeration.  The
                # precondition check returns False on
                # failure, which falls back to the executor
                # for a clearer failure.
                return True
            return True

        try:
            user32.EnumWindows(EnumWindowsProc(_callback), 0)
        except Exception:
            return (False, "EnumWindows failed on this platform")

        if matches:
            return (
                True,
                "unsaved-changes window title detected: "
                + matches[0],
            )
        return (False, "no unsaved-changes window title detected")

    # ----------------------------------------------------
    # The actual adapter entry point used by Agent Framework
    # ----------------------------------------------------

    def execute_capability(
        self,
        capability_id: str,
        arguments: Mapping[str, Any],
        approval_token: Optional[str] = None,
    ) -> ActionResult:
        """
        Build an ActionPlan for ``capability_id`` from the given
        tool-call arguments and run it through ActionExecutor.
        Returns the real ActionResult.

        For destructive capabilities
        (``ALWAYS_DESTRUCTIVE`` and the active branch of
        ``CONDITIONALLY_DESTRUCTIVE``) this method short-circuits
        BEFORE the executor is reached and returns a structured
        ``confirmation_required`` ActionResult, unless the
        caller has supplied a valid ``approval_token`` with
        format ``HUMAN-APPROVE:<capability_id>:<nonce>``
        (nonce >= 4 chars).  The token may be passed as the
        explicit ``approval_token`` kwarg or as
        ``arguments["approval_token"]``.  On a bounce the result
        carries ``success=False, executed=False, verified=False``,
        ``status="confirmation_required"`` and
        ``metadata["confirmation_required"]=True``, and the
        executor is NOT called (do NOT execute).  The adapter
        itself never injects that token.
        """

        capability_id = canonical_adapter_capability_id(capability_id)
        # Receives this request's own consumed approval record, if any.
        consumed: Dict[str, Any] = {}
        pre_check = self._risk_tier_pre_check(
            capability_id,
            arguments,
            approval_token=approval_token,
            consumed_out=consumed,
        )
        if pre_check is not None:
            return pre_check

        # Merge an explicit kwarg token into the plan arguments so
        # the executor's own confirmation gate (which reads
        # plan.parameters["confirmed"]) also passes.  The plan
        # builder promotes a valid token to confirmed=True; here
        # we only forward — never synthesize — the token.
        effective_args: Dict[str, Any] = dict(arguments)
        effective_token = _extract_approval_token(
            arguments, approval_token
        )
        if (
            effective_token is not None
            and "approval_token" not in effective_args
        ):
            effective_args["approval_token"] = effective_token
        plan = self.build_plan(
            capability_id,
            effective_args,
            consumed.get("consumed_approval"),
        )
        return self.execute_plan(plan, _approval_prechecked=True)

    # ----------------------------------------------------
    # Sync gui.paste_text path — "no running loop" fix
    # ----------------------------------------------------
    #
    # ``gui.paste_text`` previously failed when invoked from
    # synchronous code because the async entry point called
    # ``asyncio.get_running_loop()`` unconditionally, which raises
    # ``RuntimeError: no running event loop`` outside a loop.
    # This helper works from EITHER context:
    #   - no loop running -> ``asyncio.run(...)`` the async path;
    #   - loop already running -> use the sync clipboard path
    #     (direct ``execute_capability``) instead of nesting
    #     ``asyncio.run`` (which would raise).

    def execute_gui_paste_text_sync(
        self,
        text: str,
        approval_token: Optional[str] = None,
        **extra_args: Any,
    ) -> ActionResult:
        """
        Synchronous ``gui.paste_text`` entry point safe to call
        with or without a running event loop.

        Uses ``asyncio.get_running_loop()`` in a try/except: when
        no loop is running it falls back to ``asyncio.run()``
        over ``aexecute_capability``; when a loop IS running it
        takes the sync clipboard path via ``execute_capability``
        (never nests ``asyncio.run`` inside a running loop).
        """
        paste_args: Dict[str, Any] = {"text": str(text)}
        paste_args.update(extra_args or {})
        if approval_token is not None:
            paste_args.setdefault("approval_token", approval_token)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — safe to create one for the async
            # path (sync clipboard fallback via asyncio.run).
            return asyncio.run(
                self.aexecute_capability("gui.paste_text", paste_args)
            )
        else:
            # Loop already running — take the sync clipboard path
            # (direct executor routing, no nested asyncio.run).
            return self.execute_capability(
                "gui.paste_text", paste_args
            )

    # ----------------------------------------------------
    # Multi-tool chaining helper
    # ----------------------------------------------------

    def invoke_sequence(
        self, tools: List[Any]
    ) -> List[ActionResult]:
        """
        Execute a plan of tool calls in order via ActionExecutor.

        Each item in ``tools`` may be:

          - an ``ActionPlan`` (executed via ``execute_plan``), or
          - a ``dict`` with ``capability_id`` (or ``operation``)
            plus ``arguments`` (or ``parameters``/``params``) and
            an optional ``approval_token``, e.g.
            ``{"capability_id": "file.delete",
            "arguments": {"path": "C:/t.txt"},
            "approval_token": "HUMAN-APPROVE:file.delete:7f3a"}``,
            or
          - a ``(capability_id, arguments)`` / ``(capability_id,
            arguments, approval_token)`` tuple/list.

        Executes in order via ``execute_capability`` (so the
        explicit human-approval token gate and the executor's
        confirmation gate both apply).  Stops honestly on the
        first ``confirmation_required`` bounce
        (``status == "confirmation_required"`` or
        ``metadata.get("confirmation_required")``) or on the
        first failure (``success is False``) and returns ALL
        results collected so far (including the stopping one).
        Never skips a gate or fabricates ``verified``.
        """
        results: List[ActionResult] = []
        for item in tools or []:
            try:
                if isinstance(item, ActionPlan):
                    result = self.execute_plan(item)
                elif isinstance(item, Mapping):
                    cap_id = str(
                        item.get("capability_id")
                        or item.get("operation")
                        or ""
                    )
                    raw_args: Any = item.get("arguments")
                    if raw_args is None:
                        raw_args = item.get("parameters", {})
                    if raw_args is None:
                        raw_args = item.get("params", {})
                    args = (
                        dict(raw_args)
                        if isinstance(raw_args, Mapping)
                        else {}
                    )
                    # Allow stray keys at the top level of the
                    # dict to act as arguments (minus reserved).
                    for k, v in item.items():
                        if k not in (
                            "capability_id",
                            "operation",
                            "arguments",
                            "parameters",
                            "params",
                            "approval_token",
                        ) and k not in args:
                            args[k] = v
                    token = item.get("approval_token")
                    if not isinstance(token, str):
                        token = None
                    if not cap_id:
                        raise ValueError(
                            "invoke_sequence item missing "
                            "'capability_id'/'operation'"
                        )
                    result = self.execute_capability(
                        cap_id, args, approval_token=token
                    )
                elif isinstance(item, (list, tuple)):
                    if len(item) == 0:
                        continue
                    cap_id = str(item[0])
                    args = (
                        dict(item[1])
                        if len(item) > 1
                        and isinstance(item[1], Mapping)
                        else {}
                    )
                    token = (
                        str(item[2])
                        if len(item) > 2
                        and isinstance(item[2], str)
                        else None
                    )
                    result = self.execute_capability(
                        cap_id, args, approval_token=token
                    )
                else:
                    raise ValueError(
                        f"invoke_sequence: unsupported item type "
                        f"{type(item).__name__!r}"
                    )
            except Exception as exc:
                # Honest failure envelope — never raises, never
                # fabricates verified; stops the chain.
                result = ActionResult.failure_result(
                    operation="invoke_sequence",
                    target=None,
                    application=None,
                    message=f"invoke_sequence item failed: {exc}",
                    status="failed",
                    error=str(exc),
                    executed=False,
                    verified=False,
                    metadata={
                        "confirmation_required": False,
                        "sequence_error": str(exc),
                    },
                )
                results.append(result)
                break
            results.append(result)
            meta = result.metadata or {}
            is_confirmation = (
                result.status == "confirmation_required"
                or bool(meta.get("confirmation_required", False))
            )
            if is_confirmation or not result.success:
                break
        return results

    # ----------------------------------------------------
    # Async entry point - Agent Framework calls tools as
    # ``await tool.invoke(...)`` so the underlying func must be
    # awaitable.  We expose ``aexecute_capability`` and the
    # ``@tool`` wrapper below builds an async coroutine that
    # delegates to it via ``asyncio.run`` when no loop is running,
    # or directly awaits when a loop is.
    # ----------------------------------------------------

    async def aexecute_capability(
        self,
        capability_id: str,
        arguments: Mapping[str, Any],
        approval_token: Optional[str] = None,
    ) -> ActionResult:
        """
        Async wrapper around ``execute_capability``.

        The executor itself is synchronous (it talks to the OS via
        blocking calls in OSManager).  We keep the public surface
        awaitable so Agent Framework's auto-invocation loop can
        schedule it on its existing event loop without blocking
        the loop's other coroutines on a synchronous call.

        ``approval_token`` (``HUMAN-APPROVE:<capability_id>:<nonce>``)
        is threaded through to the explicit human-approval gate;
        it may also be supplied inside ``arguments``.
        """

        # ``gui.paste_text`` (and any tool invoked from sync code)
        # previously raised ``RuntimeError: no running event loop``
        # because this path called ``asyncio.get_running_loop()``
        # unconditionally.  Use try/except: when a loop is running
        # offload via ``run_in_executor``; when no loop is running
        # fall back to the sync clipboard path (direct
        # ``execute_capability``) so the call never crashes.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — sync fallback (also covers the
            # gui.paste_text clipboard path when called from plain
            # synchronous code or tests without pytest-asyncio).
            args_copy = dict(arguments)
            # Thread an explicit kwarg token into the args so the
            # approval gate sees it even on the sync path.
            if (
                approval_token is not None
                and "approval_token" not in args_copy
            ):
                args_copy["approval_token"] = approval_token
            return self.execute_capability(
                capability_id, args_copy
            )
        # Merge explicit token for the executor-thread path as well.
        args_copy = dict(arguments)
        if (
            approval_token is not None
            and "approval_token" not in args_copy
        ):
            args_copy["approval_token"] = approval_token
        # ``functools.partial``-free: run_in_executor takes a plain
        # callable, so bind via lambda to carry the token kwarg.
        import functools

        bound = functools.partial(
            self.execute_capability,
            capability_id,
            args_copy,
        )
        return await loop.run_in_executor(None, bound)

    # ----------------------------------------------------
    # Tool registration
    # ----------------------------------------------------

    def build_tool_func(
        self,
        capability_id: str,
    ) -> Callable[..., Any]:
        """
        Return a coroutine function Agent Framework can use as the
        ``func`` for a ``@tool``-decorated tool.

        The returned callable:
            - accepts the schema's keyword arguments
            - calls ``aexecute_capability`` (awaitable)
            - returns the JSON text representation of ActionResult
              (so ``FunctionTool.parse_result`` can wrap it for
              the model)
        """

        async def _tool_call(
            **kwargs: Any,
        ) -> str:
            result = await self.aexecute_capability(
                capability_id,
                kwargs,
            )
            return _action_result_to_text(result)

        _tool_call.__name__ = f"_agent_framework_{capability_id.replace('.', '_')}"
        _tool_call.__qualname__ = _tool_call.__name__

        return _tool_call


def _safe_wire_name(capability_id: str) -> str:
    """
    Return a wire-safe Agent Framework tool name derived from the
    canonical Genesis capability ID.

    OpenAI-compatible function-calling requires tool names to match
    ``^[a-zA-Z0-9_-]+$`` (no dots).  Genesis capability IDs use
    dots (for example ``application.open``); the adapter uses this
    helper to translate them to a wire-safe form
    (``application_open``) while the canonical ID stays attached
    to the tool's metadata so the model can still reason about it.
    """

    return capability_id.replace(".", "_")


def _build_tools(
    self,
) -> List[Any]:
    """
    Build the Agent Framework ``FunctionTool`` list for every
    capability in ``self.capability_ids``.

    Each tool's description is generated from the registered
    CapabilityDescriptor; the schema is the JSON schema in
    ``_ADAPTER_SCHEMAS`` (built from descriptor + executor
    parameter keys, not invented).
    """

    from agent_framework import FunctionTool

    tools: List[Any] = []
    for capability_id in self.capability_ids:
        descriptor = self.describe_capability(capability_id)
        description = _build_tool_description(
            descriptor, tool_name=capability_id
        )
        func = self.build_tool_func(capability_id)
        schema = _ADAPTER_SCHEMAS.get(capability_id)
        if schema is None:
            raise ValueError(
                f"agent_framework_adapter: no schema for "
                f"{capability_id!r}"
            )

        # =========================================================
        # SCHEMA HARDENING — close the undeclared-argument path
        # =========================================================
        # Injected HERE, centrally, rather than edited into every one
        # of the ~100 schema literals: this is the single point where
        # a schema becomes a callable tool, so one change covers every
        # capability and cannot drift from the registry the way a
        # hand-maintained list did.
        #
        # agent_framework's validator raises
        # TypeError("Unexpected argument(s) for ...") when a schema
        # sets additionalProperties False. Without it a model can pass
        # any field it likes -- including `confirmed: true`, which is
        # how the forgeable boolean used to reach the executor at all.
        #
        # Applied only after the `confirmed` sweep cleared the stale
        # call sites (2026-10-07); the first attempt broke 29 tests in
        # one file, all of them Tier 2 capabilities being handed an
        # inert `confirmed` flag by a single test helper.
        #
        # Authorization deliberately does NOT travel this way: it is
        # an AuthorizationGrant on ActionPlan.authorization, which
        # cannot be constructed from JSON at all.
        hardened = dict(schema)
        hardened["additionalProperties"] = False
        schema = hardened

        # Use the explicit ``FunctionTool`` constructor so the
        # schema and description are taken verbatim from the
        # registry rather than from docstrings / signature
        # inference (which would require ``@tool`` to wrap an
        # implementation function).  The schema is supplied via
        # ``input_model`` (which FunctionTool accepts as either
        # a Pydantic ``BaseModel`` subclass OR a JSON-schema
        # ``Mapping``); Agent Framework uses it to validate
        # tool-call arguments before invoking the underlying
        # async function.
        #
        # The wire-level tool name uses a sanitized form
        # (``application_open``) so it satisfies the OpenAI
        # function-calling rule that names match
        # ``^[a-zA-Z0-9_-]+$``.  The canonical Genesis
        # capability ID (``application.open``) is preserved
        # in ``additional_properties`` so the description and
        # any downstream tool-call response still reference it.
        wire_name = _safe_wire_name(capability_id)
        tool_obj = FunctionTool(
            name=wire_name,
            description=description,
            func=func,
            approval_mode="never_require",
            input_model=schema,
            additional_properties={
                "genesis_capability_id": capability_id,
                "provider": descriptor.provider,
                "risk_level": str(
                    getattr(descriptor, "risk_level", "") or "low"
                ),
                "side_effects": [
                    str(item)
                    for item in (
                        getattr(descriptor, "side_effects", ()) or ()
                    )
                ],
                "side_effect_class": (
                    "always_destructive"
                    if capability_id in ALWAYS_DESTRUCTIVE
                    else "conditionally_destructive"
                    if capability_id in CONDITIONALLY_DESTRUCTIVE
                    else "mutating"
                    if str(
                        getattr(descriptor, "risk_level", "") or "low"
                    ).lower() in {"medium", "high", "critical"}
                    else "read_only"
                ),
                "supported_inputs": sorted(
                    getattr(descriptor, "supported_inputs", ()) or ()
                ),
                "postconditions": [
                    str(item)
                    for item in (
                        getattr(descriptor, "postconditions", ()) or ()
                    )
                ],
                "result_envelope": [
                    "success",
                    "trustworthy_success",
                    "executed",
                    "verified",
                    "status",
                    "verification",
                    "metadata.evidence_contract",
                ],
            },
        )
        tools.append(tool_obj)

    return tools


AgentFrameworkAdapter.build_tools = _build_tools  # type: ignore[attr-defined]


# ============================================================
# CONVENIENCE BUILDER
# ============================================================


def build_default_adapter() -> AgentFrameworkAdapter:
    """
    Build an AgentFrameworkAdapter around the default Genesis
    OSManager + ActionExecutor.

    Imported lazily so importing this module does NOT eagerly
    construct OSManager (OSManager.__init__ pulls in heavy
    subsystems - GUIController, WebIntelligence, etc. - that are
    only required when the adapter is actually wired into a
    running agent).
    """

    from .os_manager import OSManager

    osm = OSManager()
    executor = ActionExecutor(osm)
    return AgentFrameworkAdapter(executor)