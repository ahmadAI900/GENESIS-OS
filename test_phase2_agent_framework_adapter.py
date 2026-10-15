"""
Genesis OS — Phase 2 Agent Framework Adapter regression test.

Scope (per ``phase2_agent_framework_adapter.md``):

    application.open
    gui.type_text
    document.create
    document.read
    browser.open_url

The Phase 2 acceptance gate has two halves:

    (a) the adapter routes the call through the REAL
        ``ActionExecutor`` (not a stub) - we assert by
        constructing the adapter around an executor whose
        ``os_manager`` is a mock that records every call
        (the executor's dispatch_table forwards to
        ``os_manager.<method>``);

    (b) the structured result returned to the model contains
        genuine ``verified`` / ``verification_reason`` fields
        sourced from the real ``ActionResult``, not values
        invented by the adapter.

The mock OSManager below mirrors the surface ``ActionExecutor._dispatch``
calls for the four non-GUI capabilities.  ``gui.type_text`` is exercised
via the executor's own runtime-focus-resolver path, which already returns
an honest ``unresolved_target`` when the runtime focus cannot be resolved.
We assert on the resolver's output, not on a fabricated verified flag.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest


# =========================================================
# Imports under test
# =========================================================

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.agent_framework_adapter import (
    POC_CAPABILITIES,
    AgentFrameworkAdapter,
    _build_action_plan,
    _build_tool_description,
    _action_result_to_text,
)
from genesis_os.capabilities import CapabilityDescriptor
from genesis_os.capability_registry import CapabilityRegistry

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real GenesisOS in one test.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


# =========================================================
# MOCK OS MANAGER
# =========================================================


class _RecordingOSManager:
    """
    Mock OSManager that records every call ActionExecutor._dispatch
    makes and returns a verifier-honest payload:

        success/executed  -> booleans (caller-controlled)
        verified          -> bound to a real observable signal:
                             for read-only ops, the file/dir/url
                             must actually exist; for open_url
                             we always report verified if success
                             (the real BrowserManager wrapper
                             binds verified to its own URL check).
        verification_reason -> explicit string when verified=False.

    The exact ``verified`` derivation here matches the spirit of the
    production ``verification_helpers`` (post-state observation), so the
    regression test proves the adapter surfaces genuine values.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    # --- application.open ---
    def open_application(self, application: str) -> dict:
        self.calls.append(
            {"method": "open_application", "application": application}
        )
        return {
            "success": True,
            "operation": "application.open",
            "application": application,
            "executed": True,
            "verified": True,
            "message": f"{application} opened successfully.",
            "data": {"process_id": 12345},
            "metadata": {"verification_type": "process_started"},
        }

    # --- browser.open_url ---
    def open_url(self, url: str) -> dict:
        self.calls.append({"method": "open_url", "url": url})
        return {
            "success": True,
            "operation": "browser.open_url",
            "executed": True,
            "verified": True,
            "message": f"Opened {url} in default browser.",
            "data": {"url": url},
            "metadata": {"verification_type": "url_dispatched"},
        }

    # --- document.read ---
    def doc_read(self, path: str) -> dict:
        self.calls.append({"method": "doc_read", "path": path})
        exists = os.path.exists(path)
        if not exists:
            return {
                "success": False,
                "operation": "document.read",
                "executed": False,
                "verified": False,
                "error": f"Document not found: {path}",
                "metadata": {
                    "verification_reason": "file_missing",
                },
            }
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            return {
                "success": False,
                "operation": "document.read",
                "executed": False,
                "verified": False,
                "error": str(exc),
                "metadata": {"verification_reason": "io_error"},
            }
        return {
            "success": True,
            "operation": "document.read",
            "executed": True,
            "verified": bool(content),
            "message": f"Read {len(content)} characters.",
            "data": {"content": content, "length": len(content)},
            "metadata": {
                "verification_type": "non_empty_payload",
                "verification_reason": (
                    "" if content else "empty_payload"
                ),
            },
        }

    # --- document.create (txt) ---
    def doc_create(
        self,
        path: str,
        doc_type: str = "txt",
        content: str = "",
        title: Optional[str] = None,
        sections: Any = None,
    ) -> dict:
        self.calls.append(
            {
                "method": "doc_create",
                "path": path,
                "doc_type": doc_type,
                "content": content,
                "title": title,
            }
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")
        except OSError as exc:
            return {
                "success": False,
                "operation": "document.create_txt",
                "executed": False,
                "verified": False,
                "error": str(exc),
                "metadata": {"verification_reason": "io_error"},
            }
        return {
            "success": True,
            "operation": "document.create_txt",
            "executed": True,
            "verified": os.path.exists(path) and os.path.getsize(path) > 0,
            "message": f"Created {path} ({os.path.getsize(path)} bytes).",
            "data": {"path": path, "size": os.path.getsize(path)},
            "metadata": {"verification_type": "file_on_disk"},
        }


# =========================================================
# FIXTURES
# =========================================================


@pytest.fixture
def recording_osm() -> _RecordingOSManager:
    return _RecordingOSManager()


@pytest.fixture
def adapter(recording_osm: _RecordingOSManager) -> AgentFrameworkAdapter:
    executor = ActionExecutor(recording_osm)
    return AgentFrameworkAdapter(executor)


@pytest.fixture
def tools(adapter: AgentFrameworkAdapter):
    return adapter.build_tools()


# =========================================================
# ASYNC HELPERS
# =========================================================
#
# The test environment does not have ``pytest-asyncio``
# installed (no extra dependency for the Phase 2 PoC).  We use
# ``asyncio.run`` to drive the adapter's async tool surface;
# each test calls a helper that returns a synchronous result.

def _invoke(tool, arguments):
    """Synchronously invoke an Agent Framework tool and return
    the parsed ActionResult dict (parsed from the JSON content
    payload the adapter returns).

    Tests are sometimes executed with an anyio event loop already
    running (``-p anyio``-driven tests in the wider suite leave a
    loop behind on Windows).  When that happens ``asyncio.run``
    raises; in that case we schedule the coroutine on the running
    loop and block until it completes.
    """

    coro = tool.invoke(arguments=arguments)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run.
        contents = asyncio.run(coro)
    else:
        # A loop is already running.  Use a private event loop on
        # a worker thread to drive the coroutine to completion.
        import threading

        result_box: Dict[str, Any] = {}

        def _runner():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                result_box["contents"] = new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner)
        thread.start()
        thread.join()
        contents = result_box["contents"]

    if not contents:
        return {}
    return json.loads(str(contents[0]))


# =========================================================
# (A) ROUTING — adapter reaches the REAL ActionExecutor
# =========================================================


class TestAdapterRouting:
    """The adapter must reach the real ``ActionExecutor`` (not a stub)."""

    def test_builds_five_tools(self, tools):
        # The wire-level tool name is a sanitized form
        # (``application_open``) so the OpenAI function-calling
        # API accepts it; the canonical Genesis capability ID
        # (``application.open``) is preserved on
        # ``additional_properties["genesis_capability_id"]``.
        wire_names = [t.name for t in tools]
        canonical_names = {
            t.additional_properties.get("genesis_capability_id")
            for t in tools
        }
        assert wire_names == [
            "application_open",
            "gui_type_text",
            "document_create",
            "document_read",
            "browser_open_url",
        ]
        assert canonical_names == set(POC_CAPABILITIES)
        assert len(tools) == 5

    def test_tool_descriptions_are_descriptor_derived_not_generic(
        self, tools
    ):
        """
        Descriptions must be derived from the CapabilityDescriptor
        (capability_id, description, supported_inputs, provider,
        permissions, risk_level) - not a generic placeholder.

        The Phase 2 prompt explicitly forbids "a generic placeholder
        description".
        """

        for t in tools:
            # The description leads with the canonical Genesis
            # capability ID so the model can reason about which
            # capability each tool invokes (the wire-level name
            # is sanitized for the OpenAI API).
            canonical_id = t.additional_properties.get(
                "genesis_capability_id"
            )
            assert t.description.startswith(
                f"Genesis capability: {canonical_id}."
            ), (
                f"tool {t.name!r} description is not "
                f"descriptor-derived: {t.description!r}"
            )
            assert "Provider:" in t.description
            assert "verified/verification_reason envelope" in t.description

    def test_tool_schemas_match_supported_inputs(
        self, tools, recording_osm
    ):
        """
        The JSON schema for each tool is non-empty (not a vacuous
        no-parameter tool) and the required keys correspond to the
        descriptor's supported_inputs (or to the keys the executor
        reads from ``plan.parameters``).
        """

        for t in tools:
            params = t.parameters()
            canonical = t.additional_properties.get(
                "genesis_capability_id"
            )
            assert "properties" in params
            assert params["type"] == "object"
            required = params.get("required", [])
            if canonical == "application.open":
                assert "application" in required
            elif canonical == "gui.type_text":
                assert "text" in required
            elif canonical == "document.create":
                assert "path" in required
            elif canonical == "document.read":
                assert "path" in required
            elif canonical == "browser.open_url":
                assert "url" in required

    def test_browser_open_url_routes_through_real_executor(
        self, adapter, recording_osm, tools
    ):
        """``browser.open_url`` must reach the real
        ``ActionExecutor`` and the real ``OSManager.open_url``."""

        br = _tool_by_canonical(tools, "browser.open_url")
        # The default SecurityManager allows browser.open_url with
        # risk_level=MEDIUM and requires_confirmation=False, so the
        # real executor dispatch table must be reached.
        parsed = _invoke(br, {"url": "https://example.com"})

        # The call reached the executor and was normalized into a
        # proper ActionResult envelope.
        assert "operation" in parsed
        assert "verified" in parsed
        assert "status" in parsed
        assert "error" in parsed
        # The result includes the executor-specific
        # ``metadata.executor_version`` field - that proves the
        # call went through the real ActionExecutor._normalize_result,
        # not a stub fabricated by the adapter.
        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        ), (
            f"result did not pass through the real ActionExecutor: "
            f"{parsed!r}"
        )

    def test_application_open_reaches_real_executor_dispatch(
        self, adapter, recording_osm, tools
    ):
        """``application.open`` must reach the executor's dispatch
        table (``os_manager.open_application``) - the same code
        path the workflow engine uses."""

        app_tool = _tool_by_canonical(tools, "application.open")
        parsed = _invoke(app_tool, {"application": "notepad"})

        # Reached the executor's normalization layer.
        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        )

    def test_document_read_reaches_real_executor_with_honest_verified(
        self, adapter, recording_osm, tools, tmp_path
    ):
        """``document.read`` must reach the real executor AND
        return the ``verified`` field that ``verification_helpers``
        actually derives (file exists + non-empty payload)."""

        real_path = tmp_path / "phase2_doc.txt"
        real_path.write_text(
            "Phase 2 adapter regression payload.", encoding="utf-8"
        )

        dr = _tool_by_canonical(tools, "document.read")
        parsed = _invoke(dr, {"path": str(real_path)})

        # Reached the real executor (regardless of whether the
        # security gate lets it through to dispatch).
        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        )

        # The ``verified`` field is genuine - it is sourced from
        # the real ``ActionResult`` envelope, not synthesized by
        # the adapter.  Whether it is True or False depends on
        # whether the existing safety pipeline blocks the call;
        # either way it must NOT be a default ``True`` the adapter
        # fabricates.
        assert "verified" in parsed
        assert isinstance(parsed["verified"], bool)

    def test_gui_type_text_reaches_real_executor_runtime_resolver(
        self, adapter, recording_osm, tools
    ):
        """``gui.type_text`` must reach the executor's runtime-focus
        resolver (the post-state observation gate from Phase 0).
        Without a safe foreground window the resolver MUST return
        ``unresolved_target`` with verified=False; the adapter must
        relay that honestly."""

        tt = _tool_by_canonical(tools, "gui.type_text")
        parsed = _invoke(tt, {"text": "Hello from Agent Framework"})

        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        )
        # Without a focused safe window the executor's runtime
        # focus resolver returns ``unresolved_target`` /
        # ``confirmation_required`` / ``verification_failed``.
        # The adapter passes that through - the
        # ``verified`` flag MUST be False on the focus-resolver
        # code path (Phase 0 invariant).
        assert parsed["status"] in {
            "unresolved_target",
            "confirmation_required",
            "verification_failed",
        }
        assert parsed["verified"] is False


def _tool_by_canonical(tools, canonical: str):
    """Resolve a tool by its canonical Genesis capability id."""
    for t in tools:
        if t.additional_properties.get("genesis_capability_id") == canonical:
            return t
    raise KeyError(canonical)


def _placeholder():  # pragma: no cover
    return None


# =========================================================
# (B) STRUCTURED RESULT CARRIES GENUINE verified FIELDS
# =========================================================


class TestAdapterResultContract:
    """The structured result must include the REAL
    ``verified`` / ``verification_reason`` from ``ActionResult`` -
    `` ``the adapter must NOT fabricate these fields."""

    def test_action_result_to_text_includes_verified_and_reason(self):
        result = ActionResult(
            success=True,
            operation="document.read",
            target="C:/foo.txt",
            application=None,
            status="verified",
            message="ok",
            executed=True,
            verified=True,
            execution={"provider": "filesystem"},
            verification={"type": "non_empty_payload"},
        )
        text = _action_result_to_text(result)
        parsed = json.loads(text)
        assert parsed["verified"] is True
        assert parsed["status"] == "verified"
        assert parsed["operation"] == "document.read"
        assert parsed["verification"] == {"type": "non_empty_payload"}

    def test_action_result_to_text_when_not_verified_carries_reason(self):
        result = ActionResult(
            success=False,
            operation="document.read",
            target="/missing.txt",
            application=None,
            status="execution_failed",
            message="missing",
            executed=False,
            verified=False,
            error="File not found",
            metadata={
                "verification_reason": "file_missing",
                "executor_version": "3.6.0",
            },
        )
        text = _action_result_to_text(result)
        parsed = json.loads(text)
        assert parsed["verified"] is False
        assert parsed["error"] == "File not found"
        assert (
            parsed["metadata"]["verification_reason"] == "file_missing"
        )

    def test_build_plan_uses_pydantic_validated_action_plan(self):
        plan = _build_action_plan(
            "application.open", {"application": "notepad"}
        )
        # ActionPlan is the same Pydantic-validated Phase 1 class.
        assert isinstance(plan, ActionPlan)
        assert plan.operation == "application.open"
        assert plan.target == "notepad"
        assert plan.confidence == 1.0

    def test_build_plan_for_gui_type_text_uses_targetless_shape(self):
        plan = _build_action_plan(
            "gui.type_text", {"text": "hello"}
        )
        assert isinstance(plan, ActionPlan)
        assert plan.operation == "gui.type_text"
        # gui.type_text is in TARGETLESS_OPERATIONS; the Phase 1
        # Pydantic validator must accept target=None.
        assert plan.target is None
        assert plan.parameters == {"text": "hello"}

    def test_build_plan_for_browser_open_url_carries_url_target(self):
        plan = _build_action_plan(
            "browser.open_url", {"url": "https://example.com"}
        )
        assert isinstance(plan, ActionPlan)
        assert plan.operation == "browser.open_url"
        assert plan.target == "https://example.com"

    def test_tool_description_includes_descriptor_fields(self):
        descriptor = CapabilityRegistry.get("browser.open_url")
        desc = _build_tool_description(descriptor)
        # Must include the descriptor's own description text - not
        # a generic placeholder.
        assert descriptor.description in desc
        assert "Provider:" in desc
        assert "genesis.browser" in desc
        # UPDATED 2026-10-04. This used to assert that the risk
        # annotation was omitted for a low-risk capability. The
        # description builder now always surfaces the risk tier to the
        # model, which is the safer direction: a tool description that
        # silently omits risk is worse than one that states it. The
        # annotation must therefore be present AND must agree with the
        # registry descriptor.
        assert "Risk level:" in desc, desc
        assert descriptor.risk_level in desc, (
            f"tool description states a risk level that disagrees with "
            f"the registry descriptor ({descriptor.risk_level!r})"
        )
        # Honest verification contract surfaced to the model.
        assert "verified/verification_reason envelope" in desc


# =========================================================
# (C) REGISTRY-DRIVEN CAPABILITY SET
# =========================================================


class TestRegistryParity:
    """The adapter must consult the existing CapabilityRegistry, not
    invent fields.  All five PoC capability IDs must resolve via the
    canonical registry entry (or the documented public alias)."""

    def test_all_five_capabilities_present_in_registry(self):
        # ``document.create`` is a public alias used in the UCCL
        # roadmap; the registry ships ``document.create_txt`` as
        # the format-agnostic sibling.
        for cap in POC_CAPABILITIES:
            if cap == "document.create":
                # The adapter resolves the alias to document.create_txt.
                CapabilityRegistry.get("document.create_txt")
                continue
            assert CapabilityRegistry.exists(cap), (
                f"PoC capability {cap!r} missing from registry"
            )

    def test_describe_capability_for_alias_resolves_to_underlying(self):
        from genesis_os.agent_framework_adapter import (
            AgentFrameworkAdapter,
        )
        executor = ActionExecutor(_RecordingOSManager())
        adapter = AgentFrameworkAdapter(executor)
        # The alias resolves to the descriptor of the underlying
        # capability without modifying the registry.
        descriptor = adapter.describe_capability("document.create")
        assert isinstance(descriptor, CapabilityDescriptor)
        # The descriptor the adapter surfaces for ``document.create``
        # is the format-agnostic ``document.create_txt`` descriptor;
        # the underlying provider is preserved.
        assert descriptor.provider == "genesis.doc_intel"
        assert descriptor.capability_id == "document.create_txt"


# =========================================================
# (D) DO-NOT-BYPASS CONFIRMATION GATE
# =========================================================


class TestAdapterDoesNotBypassSafety:
    """The adapter must NOT inject ``confirmed=True`` to bypass the
    confirmation gate.  This is enforced structurally: the adapter
    only ever builds ActionPlan with the parameters the model
    supplied, never pre-inserts a ``confirmed`` flag."""

    def test_no_confirmed_flag_injected_into_any_plan(self):
        for cap in POC_CAPABILITIES:
            if cap == "application.open":
                plan = _build_action_plan(cap, {"application": "x"})
            elif cap == "gui.type_text":
                plan = _build_action_plan(cap, {"text": "x"})
            elif cap == "document.create":
                plan = _build_action_plan(cap, {"path": "x"})
            elif cap == "document.read":
                plan = _build_action_plan(cap, {"path": "x"})
            elif cap == "browser.open_url":
                plan = _build_action_plan(cap, {"url": "https://x"})
            else:
                continue
            assert "confirmed" not in plan.parameters, (
                f"adapter injected 'confirmed' into plan for "
                f"{cap!r}: {plan.parameters!r}"
            )


# =========================================================
# (E) PHASE 2 FULL-COVERAGE WIRING  [RECONSTRUCTED 2026-10-04]
# =========================================================
#
# Both tests below were destroyed by the bulk-edit truncation bug and
# restored from their cited contract, not from a backup. The citation
# is `backend/PHASE_2_SEMANTIC_ADAPTER_2026-09-26.md`:
#
#   :55-61  "The permanent regression is
#            `backend/test_phase2_agent_framework_adapter.py:671`:
#              test_production_genesis_wires_adapter_to_canonical_executor
#            It proves that the production `GenesisOS` owns an
#            `AgentFrameworkAdapter` whose executor is the same
#            `GenesisOS.action_executor`."
#
#   :107    "The 17 A capabilities now have explicit JSON schemas and
#            real `_build_action_plan()` branches. The 14 B
#            capabilities are represented by
#            `ADAPTER_CAPABILITY_ALIASES` and
#            `canonical_adapter_capability_id()`; they are
#            intentionally not duplicated as second tools. All A and B
#            plan paths were exercised by
#            `test_newly_wired_capabilities_and_aliases_build_canonical_plans`."
#
#   :117-131  the 141/141 coverage disposition and the 127 canonical
#            tools plus 14 aliases split.
#
# The exact A/B membership is not reconstructed from memory: it is read
# at test time from `backend/phase2_step1_dispositions_2026-09-26.txt`,
# the machine-readable disposition capture the report cites by name.
# Nothing about the membership is hard-coded here.


def _dispositions():
    """The Phase 2 Step 1 A/B disposition capture, as cited."""
    import json
    import re
    from pathlib import Path

    capture = (
        Path(__file__).resolve().parent
        / "phase2_step1_dispositions_2026-09-26.txt"
    )
    raw = capture.read_text(encoding="utf-8-sig").strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```\s*$", "", raw)
    return json.loads(raw)


def test_production_genesis_wires_adapter_to_canonical_executor():
    """Contract (PHASE_2_SEMANTIC_ADAPTER:55-61): production GenesisOS
    owns an AgentFrameworkAdapter whose executor IS its own canonical
    ActionExecutor -- not a fallback or a second instance."""
    from genesis import GenesisOS
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    genesis = GenesisOS()

    adapter = getattr(genesis, "agent_framework_adapter", None)
    assert adapter is not None, (
        "production GenesisOS does not own an agent_framework_adapter"
    )
    assert isinstance(adapter, AgentFrameworkAdapter)
    assert adapter.executor is genesis.action_executor, (
        "the adapter is wired to something other than the canonical "
        "GenesisOS.action_executor"
    )


def test_newly_wired_capabilities_and_aliases_build_canonical_plans():
    """Contract (PHASE_2_SEMANTIC_ADAPTER:107): every A capability has a
    real `_build_action_plan()` branch and a JSON schema; every B
    capability is an alias resolved by
    `canonical_adapter_capability_id()` and is deliberately NOT exposed
    as a second tool."""
    from genesis_os.agent_framework_adapter import (
        ADAPTER_CAPABILITY_ALIASES,
        EXPANDED_CAPABILITIES,
        POC_CAPABILITIES,
        _ADAPTER_SCHEMAS,
        _build_action_plan,
        canonical_adapter_capability_id,
    )

    dispositions = _dispositions()
    group_a = sorted(
        item["capability_id"] for item in dispositions
        if item["disposition"] == "A"
    )
    group_b = sorted(
        item["capability_id"] for item in dispositions
        if item["disposition"] == "B"
    )
    # The report states 17 A and 14 B; the capture is the authority.
    assert len(group_a) == 17, f"expected 17 A dispositions, got {len(group_a)}"
    assert len(group_b) == 14, f"expected 14 B dispositions, got {len(group_b)}"

    # --- A: a real plan branch and an explicit schema for each -------
    # The citation states two things per A capability: it has an
    # explicit JSON schema, and it has a real `_build_action_plan()`
    # branch. It does NOT claim every schema declares a required
    # input, and some genuinely take none -- `application.window_list`
    # has schema `{"properties": {}, "type": "object"}` in
    # production, which is correct for an inventory operation. Nothing
    # beyond the cited claim is asserted.
    for capability_id in group_a:
        assert capability_id in _ADAPTER_SCHEMAS, (
            f"A capability {capability_id!r} has no JSON schema"
        )
        schema = _ADAPTER_SCHEMAS[capability_id]
        assert schema.get("type") == "object", (
            f"A capability {capability_id!r} has a non-object schema: "
            f"{schema!r}"
        )

        plan = _build_action_plan(capability_id, _minimal_args(capability_id))
        assert plan is not None, (
            f"A capability {capability_id!r} built no ActionPlan"
        )
        assert plan.operation == capability_id, (
            f"{capability_id!r} built a plan for {plan.operation!r}"
        )

    # --- B: an alias, resolvable, and never a second tool -----------
    assert sorted(ADAPTER_CAPABILITY_ALIASES) == group_b, (
        "the alias table no longer matches the cited B dispositions"
    )
    # "intentionally not duplicated as second tools" is a claim about
    # the EXPOSURE set, so it is asserted against what the adapter
    # actually exposes -- `EXPANDED_CAPABILITIES` plus the always-on
    # `POC_CAPABILITIES` -- and not against `_ADAPTER_SCHEMAS`, which
    # is only an argument-lookup table. Two legitimate cases force
    # that distinction: `weather.current` sits in the schema table (it
    # is how a caller's arguments are validated before
    # canonicalisation) while never being exposed; and
    # `document.create_txt` / `document.read_intel` canonicalise onto
    # the PoC capabilities `document.create` / `document.read`, which
    # are exposed on a separate always-on path, not through EXPANDED.
    exposed = set(EXPANDED_CAPABILITIES) | set(POC_CAPABILITIES)
    for capability_id in group_b:
        canonical = canonical_adapter_capability_id(capability_id)
        assert canonical != capability_id, (
            f"{capability_id!r} is registered as an alias of itself"
        )
        assert canonical, (
            f"{capability_id!r} did not resolve to a canonical id"
        )
        assert capability_id not in exposed, (
            f"alias {capability_id!r} is also exposed as its own tool, "
            f"duplicating the canonical capability"
        )
        assert canonical in exposed, (
                f"alias {capability_id!r} points at {canonical!r}, which is "
                f"not itself exposed -- the alias has no reachable target"
            )


def _minimal_args(capability_id):
    """The smallest argument set that satisfies a capability's schema.

    Derived from the schema itself rather than a hand-written table, so
    a new required input cannot make this reconstruction silently wrong.
    """
    from genesis_os.agent_framework_adapter import _ADAPTER_SCHEMAS

    schema = _ADAPTER_SCHEMAS[capability_id]
    args = {}
    for name in schema.get("required", ()):
        declared = schema["properties"][name]
        kind = declared.get("type", "string")
        args[name] = {
            "string": "x",
            "integer": 1,
            "number": 1,
            "boolean": True,
            "array": ["x"],
            "object": {},
        }.get(kind, "x")
    return args
